"""Actual HTTP/SQL/process fault witnesses, separate from Agent success trials."""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import httpx

from .caseflow import Gateway
from .caseflow_eval import request, seed, task_corpus
from .caseflow_runtime import services
from .common import ROOT, db, digest, freeze, write_json, rate


NAMES = (
    "concurrent_same_operation",
    "lost_response_restart",
    "process_exit_after_commit",
    "expired_before_write",
    "revoked_after_partial",
    "expired_after_partial",
    "approval_wrong_proposal",
    "same_operation_changed_payload",
    "scope_denied",
    "concurrent_version_before_commit",
    "newer_version_and_stale_index",
    "index_worker_restart",
)


def run_witnesses(out):
    freeze(
        out,
        {
            "names": NAMES,
            "scope": "Deterministic controlled faults against two real HTTP/PostgreSQL services; no LLM capability or general reliability claim",
            "authorization_policy": "Check before every new side-effect dispatch, retain already authorized knowledge commit; partial state is not rollback",
            "source": {
                n: digest((ROOT / "src/caseflow_agent" / n).read_bytes())
                for n in (
                    "caseflow.py",
                    "caseflow_backend.py",
                    "caseflow_faults.py",
                    "caseflow_fault_worker.py",
                )
            },
        },
    )
    if (out / "summary.json").exists():
        return json.loads((out / "summary.json").read_text())
    rows = []
    # Index pause is global to this task's service. Run this suite alone after
    # Agent trials, so no unrelated task or user service is affected.
    with services() as cfg:
        for name in NAMES:
            folder = out / name
            folder.mkdir(exist_ok=True)
            task = dict(task_corpus()[0])
            task["id"] = "witness-" + name
            task["policy"] = {"approval": "approve"}
            if name == "lost_response_restart":
                task["policy"]["drop_knowledge_response_once"] = True
            if name == "scope_denied":
                task["family"] = "scope"
            fixture = seed(cfg, task, folder)

            def gateway():
                return Gateway(
                    folder / "gateway.sqlite",
                    scope=fixture["session_scope"],
                    subject="synthetic-operator",
                    knowledge_url=cfg["knowledge"],
                    tickets_url=cfg["tickets"],
                    internal_token=cfg["token"],
                    user_policy=task["policy"],
                    skills_path=ROOT / "skills",
                )

            g = gateway()
            events = []
            started = time.monotonic()

            def call(tool, **args):
                r = g.call(tool, args)
                events.append({"tool": tool, "result": r})
                return r

            def final():
                return request(
                    cfg, "knowledge", "GET", "/items/" + fixture["knowledge_id"]
                ), request(cfg, "tickets", "GET", "/items/" + fixture["ticket_id"])

            try:
                p = call(
                    "proposals.create",
                    ticket_id=fixture["ticket_id"],
                    knowledge_id=fixture["knowledge_id"],
                    ticket_version=1,
                    knowledge_version=1,
                    content=task["new_content"],
                )
                if name == "scope_denied":
                    k, t = final()
                    passed = (
                        not p["ok"]
                        and p["error"] == "scope_denied"
                        and k["version"] == 1
                        and t["version"] == 1
                    )
                else:
                    pid = p["data"]["proposal_id"]
                    a = call("approvals.request", proposal_id=pid)
                    aid = a["data"]["approval_id"]
                    call("operations.begin", proposal_id=pid, approval_id=aid)
                    if name == "concurrent_same_operation":
                        with ThreadPoolExecutor(2) as pool:
                            events.extend(
                                pool.map(
                                    lambda _: gateway().call(
                                        "workflow.apply",
                                        {"proposal_id": pid, "approval_id": aid},
                                    ),
                                    range(2),
                                )
                            )
                        k, t = final()
                        passed = (
                            k["version"] == 2
                            and t["version"] == 2
                            and t["knowledge_version"] == 2
                        )
                    elif name == "lost_response_restart":
                        first = call("workflow.apply", proposal_id=pid, approval_id=aid)
                        g = gateway()
                        second = call(
                            "workflow.apply", proposal_id=pid, approval_id=aid
                        )
                        k, t = final()
                        passed = (
                            not first["ok"]
                            and second["ok"]
                            and k["version"] == 2
                            and t["version"] == 2
                        )
                    elif name == "process_exit_after_commit":
                        env = {
                            k: v
                            for k, v in os.environ.items()
                            if not any(
                                x in k for x in ("API_KEY", "ANTHROPIC_AUTH_TOKEN")
                            )
                        }
                        env.update(
                            CASEFLOW_WITNESS=json.dumps(
                                {
                                    "ledger": str(
                                        (folder / "gateway.sqlite").resolve()
                                    ),
                                    "scope": fixture["session_scope"],
                                    "policy": task["policy"],
                                    "operation_id": pid,
                                    "approval_id": aid,
                                }
                            ),
                            CASEFLOW_KNOWLEDGE_URL=cfg["knowledge"],
                            CASEFLOW_TICKETS_URL=cfg["tickets"],
                            CASEFLOW_INTERNAL_TOKEN=cfg["token"],
                        )
                        child = subprocess.run(
                            [sys.executable, "-m", "caseflow_agent.caseflow_fault_worker"],
                            env=env,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                        events.append(
                            {
                                "child_exit": child.returncode,
                                "stdout": child.stdout.strip(),
                            }
                        )
                        g = gateway()
                        r = call("workflow.apply", proposal_id=pid, approval_id=aid)
                        k, t = final()
                        passed = (
                            child.returncode == 73
                            and r["ok"]
                            and k["version"] == 2
                            and t["version"] == 2
                        )
                    elif name in (
                        "expired_before_write",
                        "revoked_after_partial",
                        "expired_after_partial",
                    ):
                        if name != "expired_before_write":
                            call(
                                "knowledge.apply_operation",
                                operation_id=pid,
                                approval_id=aid,
                            )
                        with db(g.path) as c:
                            c.execute(
                                "UPDATE approvals SET "
                                + (
                                    "revoked=1"
                                    if name == "revoked_after_partial"
                                    else "expires=0"
                                )
                                + " WHERE id=?",
                                (aid,),
                            )
                        r = call("workflow.apply", proposal_id=pid, approval_id=aid)
                        k, t = final()
                        passed = (
                            not r["ok"]
                            and r["error"] == "approval_denied_expired_or_revoked"
                            and k["version"]
                            == (1 if name == "expired_before_write" else 2)
                            and t["version"] == 1
                        )
                    elif name == "approval_wrong_proposal":
                        q = call(
                            "proposals.create",
                            ticket_id=fixture["ticket_id"],
                            knowledge_id=fixture["knowledge_id"],
                            ticket_version=1,
                            knowledge_version=1,
                            content=task["new_content"] + "\n修改后的未批准正文",
                        )
                        r = call(
                            "workflow.apply",
                            proposal_id=q["data"]["proposal_id"],
                            approval_id=aid,
                        )
                        k, t = final()
                        passed = (
                            not r["ok"]
                            and r["error"] == "approval_binding_invalid"
                            and k["version"] == 1
                            and t["version"] == 1
                        )
                    elif name == "same_operation_changed_payload":
                        call(
                            "knowledge.apply_operation",
                            operation_id=pid,
                            approval_id=aid,
                        )
                        try:
                            request(
                                cfg,
                                "knowledge",
                                "POST",
                                "/apply",
                                json={
                                    "operation_id": pid,
                                    "knowledge_id": fixture["knowledge_id"],
                                    "expected_version": 1,
                                    "content": "tampered",
                                    "scope": fixture["session_scope"],
                                    "approval_digest": p["data"]["digest"],
                                },
                            )
                            denied = False
                        except httpx.HTTPStatusError as exc:
                            denied = (
                                exc.response.status_code == 409
                                and exc.response.json().get("detail")
                                == "idempotency_payload_conflict"
                            )
                        k, t = final()
                        passed = (
                            denied
                            and k["version"] == 2
                            and k["content"] == task["new_content"]
                            and t["version"] == 1
                        )
                    elif name in (
                        "concurrent_version_before_commit",
                        "newer_version_and_stale_index",
                    ):
                        if name == "newer_version_and_stale_index":
                            request(
                                cfg,
                                "knowledge",
                                "POST",
                                "/control/index",
                                json={"paused": True},
                            )
                            call(
                                "knowledge.apply_operation",
                                operation_id=pid,
                                approval_id=aid,
                            )
                            expected = 2
                        else:
                            expected = 1
                        request(
                            cfg,
                            "knowledge",
                            "POST",
                            "/apply",
                            json={
                                "operation_id": "other-" + pid,
                                "knowledge_id": fixture["knowledge_id"],
                                "expected_version": expected,
                                "content": "# 并发编辑\n保留更新的内容。",
                                "scope": fixture["session_scope"],
                                "approval_digest": "independent-fixture-approval",
                            },
                        )
                        request(
                            cfg,
                            "knowledge",
                            "POST",
                            "/control/index",
                            json={"paused": False},
                        )
                        for _ in range(150):
                            k, t = final()
                            if (
                                k["status"] == "searchable"
                                and k["indexed_version"] == expected + 1
                            ):
                                break
                            time.sleep(0.02)
                        r = call("workflow.apply", proposal_id=pid, approval_id=aid)
                        k, t = final()
                        old = (
                            request(cfg, "knowledge", "GET", "/receipts/" + pid)
                            if name == "newer_version_and_stale_index"
                            else None
                        )
                        events.append({"old_receipt": old})
                        passed = (
                            not r["ok"]
                            and k["version"] == expected + 1
                            and k["content"] == "# 并发编辑\n保留更新的内容。"
                            and k["indexed_version"] == expected + 1
                            and t["version"] == 1
                            and (old is None or old["state"] == "superseded")
                        )
                    elif name == "index_worker_restart":
                        request(
                            cfg,
                            "knowledge",
                            "POST",
                            "/control/index",
                            json={"paused": True},
                        )
                        call(
                            "knowledge.apply_operation",
                            operation_id=pid,
                            approval_id=aid,
                        )
                        events.append(
                            {
                                "pending_receipt": request(
                                    cfg, "knowledge", "GET", "/receipts/" + pid
                                )
                            }
                        )
                        events.append(
                            {"actual_backend_restart": cfg["_restart"]("knowledge")}
                        )
                        request(
                            cfg,
                            "knowledge",
                            "POST",
                            "/control/index",
                            json={"paused": False},
                        )
                        for _ in range(150):
                            if call("knowledge.index_status", operation_id=pid)["data"][
                                "ready"
                            ]:
                                break
                            time.sleep(0.02)
                        r = call("workflow.apply", proposal_id=pid, approval_id=aid)
                        k, t = final()
                        passed = r["ok"] and k["version"] == 2 and t["version"] == 2
                    else:
                        raise ValueError(name)
                row = {
                    "name": name,
                    "passed": bool(passed),
                    "knowledge": k,
                    "ticket": t,
                    "events": events,
                    "elapsed_ms": (time.monotonic() - started) * 1000,
                }
            except Exception as exc:
                row = {
                    "name": name,
                    "passed": False,
                    "error_type": type(exc).__name__,
                    "events": events,
                }
            finally:
                request(
                    cfg, "knowledge", "POST", "/control/index", json={"paused": False}
                )
            write_json(folder / "result.json", row)
            rows.append(row)
            print(name, row["passed"], flush=True)
    result = {
        "coverage": rate(sum(r["passed"] for r in rows), len(rows)),
        "rows": rows,
        "limit": "Controlled deterministic fault witnesses, not measured field reliability. Index restart terminates and restarts the actual task-owned knowledge HTTP/worker process with a pending PostgreSQL job.",
    }
    write_json(out / "summary.json", result)
    return result


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    a = p.parse_args()
    run_witnesses(Path(a.out))
