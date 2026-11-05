from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value) -> str:
    raw = value if isinstance(value, bytes) else canonical(value).encode()
    return hashlib.sha256(raw).hexdigest()


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def append_jsonl(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(canonical(data) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_jsonl(path: Path):
    return (
        [json.loads(line) for line in path.read_bytes().split(b"\n") if line.strip()]
        if path.exists()
        else []
    )


def percentile(values, quantile):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * quantile) - 1)] if values else None


def rate(n, d):
    return {"num": n, "den": d, "value": n / d if d else None}


@contextlib.contextmanager
def db(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def freeze(directory: Path, protocol: dict):
    protocol = json.loads(canonical(protocol))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "protocol.lock.json"
    protocol = dict(protocol, protocol_sha256=digest(protocol))
    if path.exists() and json.loads(path.read_text()) != protocol:
        raise ValueError(
            "A frozen protocol cannot be overwritten; choose a new run directory"
        )
    if not path.exists():
        write_json(path, protocol)
    return protocol


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """Cross-thread/process reservation prevents unmetered concurrent API calls."""

    def __init__(self, path: Path, limit_usd=75):
        self.path, self.limit = path, limit_usd
        with db(path) as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, status TEXT, reserved REAL, cost REAL, input_tokens INTEGER, output_tokens INTEGER, created TEXT)"
            )
            columns = {r[1] for r in c.execute("PRAGMA table_info(calls)")}
            for name in ("label", "request_sha256"):
                if name not in columns:
                    c.execute(f"ALTER TABLE calls ADD COLUMN {name} TEXT")

    def reserve(self, amount, *, label="", request_sha256=""):
        with db(self.path) as c:
            c.execute("BEGIN IMMEDIATE")
            used = c.execute(
                "SELECT COALESCE(SUM(CASE WHEN status='reserved' THEN reserved ELSE cost END),0) FROM calls"
            ).fetchone()[0]
            if used + amount > self.limit:
                raise BudgetExceeded("Global API budget exhausted")
            key = uuid.uuid4().hex
            c.execute(
                "INSERT INTO calls(id,status,reserved,cost,input_tokens,output_tokens,created,label,request_sha256) VALUES(?,?,?,?,?,?,?,?,?)",
                (key, "reserved", amount, 0, 0, 0, utc(), label, request_sha256),
            )
            return key

    def settle(self, key, usage, cost, *, unknown_billing=False):
        with db(self.path) as c:
            c.execute(
                "UPDATE calls SET status=?,cost=?,input_tokens=?,output_tokens=? WHERE id=?",
                (
                    "unknown_billing" if unknown_billing else "completed",
                    cost,
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                    key,
                ),
            )

    def summary(self):
        with db(self.path) as c:
            return dict(
                c.execute(
                    "SELECT COUNT(*) calls, COALESCE(SUM(CASE WHEN status='reserved' THEN reserved ELSE cost END),0) cost_upper_bound_usd,COALESCE(SUM(CASE WHEN status='completed' THEN cost ELSE 0 END),0) known_usage_peak_equivalent_usd,COALESCE(SUM(CASE WHEN status='reserved' THEN reserved ELSE 0 END),0) pending_reserved_usd,COALESCE(SUM(CASE WHEN status='unknown_billing' THEN cost ELSE 0 END),0) charge_unknown_upper_bound_usd,COALESCE(SUM(input_tokens),0) input_tokens,COALESCE(SUM(output_tokens),0) output_tokens FROM calls"
                ).fetchone()
            )

    def trial_usage(self, label):
        with db(self.path) as c:
            return dict(
                c.execute(
                    "SELECT COALESCE(SUM(input_tokens),0) input_tokens,COALESCE(SUM(output_tokens),0) output_tokens,COALESCE(SUM(CASE WHEN status!='completed' THEN 1 ELSE 0 END),0) unknown_usage_calls,COALESCE(SUM(CASE WHEN status='reserved' THEN reserved ELSE cost END),0) cost_upper_bound_usd FROM calls WHERE label=?",
                    (label,),
                ).fetchone()
            )
