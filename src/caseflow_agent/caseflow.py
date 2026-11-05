"""Durable gateway for two real business services, with synthetic user policy.

No proposal field can set actor identity, approval decisions, backend URLs or
internal credentials. The caller receives capabilities, not those secrets.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
import uuid

import httpx

from .common import db, digest, append_jsonl, utc


class BusinessError(ValueError):
    def __init__(self, code, detail=""):
        self.code, self.detail = code, detail
        super().__init__(code)


class Gateway:
    def __init__(
        self,
        path: Path,
        *,
        scope,
        subject,
        knowledge_url,
        tickets_url,
        internal_token,
        user_policy=None,
        skills_path=None,
    ):
        self.path, self.scope, self.subject = path, scope, subject
        self.urls = {"knowledge": knowledge_url, "tickets": tickets_url}
        self.token = internal_token
        self.policy = user_policy or {"approval": "approve"}
        self.skills_path = skills_path
        self.clarified = None
        self.drop_consumed = False
        with db(path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,digest TEXT,payload TEXT)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,proposal_id TEXT,digest TEXT,subject TEXT,decision TEXT,expires REAL,revoked INT DEFAULT 0)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,proposal_id TEXT,digest TEXT,state TEXT,detail TEXT)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS interactions(id INTEGER PRIMARY KEY,kind TEXT,request TEXT,response TEXT,created TEXT)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS injected_faults(name TEXT PRIMARY KEY,consumed INT NOT NULL)"
            )

    def http(self, service, method, path, **kwargs):
        with httpx.Client(timeout=15, trust_env=False) as client:
            r = client.request(
                method,
                self.urls[service] + path,
                headers={"x-internal-token": self.token},
                **kwargs,
            )
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", "backend_error")
            except ValueError:
                detail = "backend_error"
            raise BusinessError(str(detail), str(r.status_code))
        return r.json()

    def read(self, service, key):
        row = self.http(service, "GET", "/items/" + key)
        if row["scope"] != self.scope:
            raise BusinessError("scope_denied")
        return row

    def _proposal(self, key):
        with db(self.path) as c:
            row = c.execute("SELECT * FROM proposals WHERE id=?", (key,)).fetchone()
        if not row:
            raise BusinessError("proposal_not_found")
        return dict(row), json.loads(row["payload"])

    def propose(self, args):
        ticket = self.read("tickets", args["ticket_id"])
        knowledge = self.read("knowledge", args["knowledge_id"])
        if ticket["knowledge_id"] != knowledge["id"]:
            raise BusinessError("knowledge_link_conflict")
        if (
            ticket["version"] != args["ticket_version"]
            or knowledge["version"] != args["knowledge_version"]
        ):
            raise BusinessError("proposal_version_conflict")
        if (
            self.policy.get("expected_knowledge_version") is not None
            and knowledge["version"] != self.policy["expected_knowledge_version"]
        ):
            raise BusinessError("user_version_precondition_failed")
        if "设备型号待补充" in ticket["description"] and not self.clarified:
            raise BusinessError(
                "clarification_required",
                "Ask the user for the missing device model; do not guess",
            )
        payload = {
            "ticket_id": ticket["id"],
            "knowledge_id": knowledge["id"],
            "ticket_version": args["ticket_version"],
            "knowledge_version": args["knowledge_version"],
            "content": args["content"],
            "scope": self.scope,
            "subject": self.subject,
        }
        if not str(payload["content"]).strip():
            raise BusinessError("empty_content")
        key, ph = uuid.uuid4().hex, digest(payload)
        with db(self.path) as c:
            c.execute(
                "INSERT INTO proposals VALUES(?,?,?)",
                (key, ph, json.dumps(payload, ensure_ascii=False)),
            )
        return {
            "proposal_id": key,
            "digest": ph,
            "payload": payload,
            "approval_required": True,
        }

    def request_approval(self, proposal_id):
        row, payload = self._proposal(proposal_id)
        # The simulator returns only a declared user decision, not gold actions.
        decision = (
            "approved" if self.policy.get("approval") == "approve" else "rejected"
        )
        key = uuid.uuid4().hex
        expires = time.time() + self.policy.get("approval_ttl_seconds", 600)
        with db(self.path) as c:
            c.execute(
                "INSERT INTO approvals VALUES(?,?,?,?,?,?,0)",
                (key, proposal_id, row["digest"], self.subject, decision, expires),
            )
            c.execute(
                "INSERT INTO interactions(kind,request,response,created) VALUES(?,?,?,?)",
                ("approval_simulator", row["digest"], decision, utc()),
            )
        return {
            "approval_id": key,
            "decision": decision,
            "proposal_digest": row["digest"],
            "expires_at_epoch": expires,
            "origin": "predeclared_synthetic_user_policy",
        }

    def approve_check(self, proposal_id, approval_id):
        row, payload = self._proposal(proposal_id)
        with db(self.path) as c:
            a = c.execute(
                "SELECT * FROM approvals WHERE id=?", (approval_id,)
            ).fetchone()
        if (
            not a
            or a["proposal_id"] != proposal_id
            or a["digest"] != row["digest"]
            or a["subject"] != self.subject
        ):
            raise BusinessError("approval_binding_invalid")
        if a["decision"] != "approved" or a["revoked"] or a["expires"] <= time.time():
            raise BusinessError("approval_denied_expired_or_revoked")
        return row, payload

    def begin(self, proposal_id, approval_id):
        row, payload = self.approve_check(proposal_id, approval_id)
        op = proposal_id
        with db(self.path) as c:
            c.execute(
                "INSERT OR IGNORE INTO operations VALUES(?,?,?,?,?)",
                (op, proposal_id, row["digest"], "approved", ""),
            )
            existing = c.execute(
                "SELECT * FROM operations WHERE id=?", (op,)
            ).fetchone()
            if existing["digest"] != row["digest"]:
                raise BusinessError("operation_payload_conflict")
        return {"operation_id": op, "state": existing["state"]}

    def _set(self, op, state, detail=""):
        with db(self.path) as c:
            c.execute(
                "UPDATE operations SET state=?,detail=? WHERE id=?", (state, detail, op)
            )

    def _operation(self, op):
        with db(self.path) as c:
            r = c.execute("SELECT * FROM operations WHERE id=?", (op,)).fetchone()
        if not r:
            raise BusinessError("operation_not_found")
        return dict(r)

    def knowledge_apply(self, op, approval_id):
        operation = self._operation(op)
        row, payload = self.approve_check(operation["proposal_id"], approval_id)
        request = {
            "operation_id": op,
            "knowledge_id": payload["knowledge_id"],
            "expected_version": payload["knowledge_version"],
            "content": payload["content"],
            "scope": self.scope,
            "approval_digest": row["digest"],
        }
        result = self.http("knowledge", "POST", "/apply", json=request)
        self._set(op, "knowledge_pending")
        if self.policy.get("drop_knowledge_response_once"):
            with db(self.path) as c:
                c.execute("BEGIN IMMEDIATE")
                consumed = c.execute(
                    "SELECT consumed FROM injected_faults WHERE name='knowledge_response' "
                ).fetchone()
                first = not consumed
                if first:
                    c.execute(
                        "INSERT INTO injected_faults VALUES('knowledge_response',1)"
                    )
            if first:
                raise BusinessError(
                    "injected_response_lost_after_real_commit",
                    "Retry with the same operation; do not create a new proposal",
                )
        return result

    def knowledge_status(self, op):
        operation = self._operation(op)
        row, payload = self._proposal(operation["proposal_id"])
        receipt = self.http("knowledge", "GET", "/receipts/" + op)
        current = self.read("knowledge", payload["knowledge_id"])
        if (
            receipt["state"] == "superseded"
            or current["version"] != receipt["version_number"]
        ):
            self._set(op, "conflict", "knowledge_changed_after_commit")
            raise BusinessError("knowledge_changed_after_commit")
        ready = (
            receipt["state"] == "ready"
            and current["status"] == "searchable"
            and current["indexed_version"] == receipt["version_number"]
        )
        if ready:
            self._set(op, "knowledge_ready")
        return {"ready": ready, "receipt": receipt, "current": current}

    def ticket_apply(self, op, approval_id):
        operation = self._operation(op)
        row, payload = self.approve_check(operation["proposal_id"], approval_id)
        status = self.knowledge_status(op)
        if not status["ready"]:
            raise BusinessError("knowledge_not_searchable_yet")
        result = self.http(
            "tickets",
            "POST",
            "/apply",
            json={
                "operation_id": op,
                "ticket_id": payload["ticket_id"],
                "expected_version": payload["ticket_version"],
                "knowledge_id": payload["knowledge_id"],
                "knowledge_version": status["current"]["version"],
                "scope": self.scope,
            },
        )
        self._set(op, "ticket_applied")
        return result

    def verify(self, op):
        operation = self._operation(op)
        row, payload = self._proposal(operation["proposal_id"])
        ks = self.knowledge_status(op)
        ticket = self.read("tickets", payload["ticket_id"])
        if (
            not ks["ready"]
            or ticket["status"] != "closed"
            or ticket["knowledge_version"] != ks["current"]["version"]
        ):
            self._set(op, "conflict", "final_state_mismatch")
            raise BusinessError("final_state_mismatch")
        self._set(op, "verified")
        return {
            "operation_id": op,
            "state": "verified",
            "ticket": ticket,
            "knowledge": ks["current"],
            "verified_at": utc(),
        }

    def apply_workflow(self, proposal_id, approval_id):
        result = self.begin(proposal_id, approval_id)
        op = result["operation_id"]
        if result["state"] == "verified":
            return self.verify(op)
        self.knowledge_apply(op, approval_id)
        for _ in range(40):
            if self.knowledge_status(op)["ready"]:
                break
            time.sleep(0.05)
        self.ticket_apply(op, approval_id)
        return self.verify(op)

    def status(self, op):
        r = self._operation(op)
        return {"operation_id": op, "state": r["state"], "detail": r["detail"]}

    def ask_user(self, question):
        reply = (
            self.policy.get("device_model")
            if any(k in question.lower() for k in ("型号", "model", "device"))
            else None
        )
        if reply:
            self.clarified = reply
        response = {
            "reply": reply,
            "available": bool(reply),
            "origin": "predeclared_synthetic_user_facts",
        }
        with db(self.path) as c:
            c.execute(
                "INSERT INTO interactions(kind,request,response,created) VALUES(?,?,?,?)",
                ("clarification_simulator", question, json.dumps(response), utc()),
            )
        return response

    def call(self, name, arguments):
        try:
            a = arguments
            if name in ("tickets.get", "knowledge.get"):
                data = self.read(name.split(".")[0], a["id"])
            elif name in ("tickets.search", "knowledge.search"):
                data = self.http(
                    name.split(".")[0],
                    "GET",
                    "/items",
                    params={"scope": self.scope, "q": a.get("query", "")},
                )
            elif name == "proposals.create":
                data = self.propose(a)
            elif name == "proposals.get":
                r, data = self._proposal(a["proposal_id"])
                data = dict(data, digest=r["digest"])
            elif name == "approvals.request":
                data = self.request_approval(a["proposal_id"])
            elif name == "approvals.get":
                with db(self.path) as c:
                    row = c.execute(
                        "SELECT id,decision,digest,expires,revoked FROM approvals WHERE id=?",
                        (a["approval_id"],),
                    ).fetchone()
                if not row:
                    raise BusinessError("approval_not_found")
                data = dict(row)
            elif name in ("workflow.status", "operations.status"):
                data = self.status(a["operation_id"])
            elif name == "workflow.apply":
                data = self.apply_workflow(a["proposal_id"], a["approval_id"])
            elif name == "operations.begin":
                data = self.begin(a["proposal_id"], a["approval_id"])
            elif name == "knowledge.apply_operation":
                data = self.knowledge_apply(a["operation_id"], a["approval_id"])
            elif name == "knowledge.index_status":
                data = self.knowledge_status(a["operation_id"])
            elif name == "tickets.apply_operation":
                data = self.ticket_apply(a["operation_id"], a["approval_id"])
            elif name == "operations.verify":
                data = self.verify(a["operation_id"])
            elif name == "host.ask_user":
                data = self.ask_user(a["question"])
            elif name == "host.load_skill":
                if a["name"] not in (
                    "ticket-resolution",
                    "knowledge-revision",
                    "interrupted-operation",
                ):
                    raise BusinessError("skill_not_allowlisted")
                data = {
                    "name": a["name"],
                    "content": (self.skills_path / a["name"] / "SKILL.md").read_text(),
                }
            else:
                raise BusinessError("tool_not_found")
            result = {"ok": True, "data": data}
        except (BusinessError, KeyError, TypeError, httpx.HTTPError) as exc:
            result = {
                "ok": False,
                "error": getattr(exc, "code", "invalid_arguments"),
                "detail": getattr(exc, "detail", ""),
            }
        append_jsonl(
            self.path.with_suffix(".events.jsonl"),
            {"at": utc(), "tool": name, "arguments": arguments, "result": result},
        )
        return result
