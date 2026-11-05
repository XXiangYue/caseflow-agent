from __future__ import annotations
import asyncio
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import asyncpg
import httpx

from .common import ROOT


async def databases():
    conn = await asyncpg.connect("postgresql://postgres@127.0.0.1:57543/postgres")
    try:
        existing = {
            r["datname"] for r in await conn.fetch("SELECT datname FROM pg_database")
        }
        for name in ("outcomes_knowledge", "outcomes_tickets"):
            if name not in existing:
                await conn.execute("CREATE DATABASE " + name)
    finally:
        await conn.close()


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def services():
    asyncio.run(databases())
    token = secrets.token_urlsafe(32)
    processes, handles = [], []
    urls = {}
    launch = {}
    try:
        for role in ("knowledge", "tickets"):
            port = free_port()
            env = {
                k: v
                for k, v in os.environ.items()
                if not any(s in k for s in ("API_KEY", "ANTHROPIC_AUTH_TOKEN"))
            }
            env.update(
                CASEFLOW_ROLE=role,
                CASEFLOW_DATABASE_URL=f"postgresql+asyncpg://postgres@127.0.0.1:57543/outcomes_{role}",
                CASEFLOW_INTERNAL_TOKEN=token,
                CASEFLOW_PORT=str(port),
            )
            ROOT.joinpath("runtime").mkdir(exist_ok=True)
            log = open(ROOT / "runtime" / f"caseflow_{role}.log", "a")
            handles.append(log)
            p = subprocess.Popen(
                [sys.executable, "-m", "caseflow_agent.caseflow_backend"],
                env=env,
                stdout=log,
                stderr=log,
            )
            processes.append(p)
            launch[role] = (env, log, p)
            url = f"http://127.0.0.1:{port}"
            for _ in range(100):
                if p.poll() is not None:
                    raise RuntimeError(
                        "Backend startup failed; see sanitized task-owned service log"
                    )
                try:
                    if (
                        httpx.get(
                            url + "/health", timeout=0.5, trust_env=False
                        ).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise TimeoutError("Backend startup timed out")
            urls[role] = url

        def restart(role):
            env, log, old = launch[role]
            old.terminate()
            old.wait(timeout=10)
            fresh = subprocess.Popen(
                [sys.executable, "-m", "caseflow_agent.caseflow_backend"],
                env=env,
                stdout=log,
                stderr=log,
            )
            processes.append(fresh)
            launch[role] = (env, log, fresh)
            for _ in range(100):
                try:
                    if (
                        httpx.get(
                            urls[role] + "/health", timeout=0.5, trust_env=False
                        ).status_code
                        == 200
                    ):
                        return {"old_pid": old.pid, "new_pid": fresh.pid}
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            raise TimeoutError("Restarted task backend did not become ready")

        yield dict(urls, token=token, _restart=restart)
    finally:
        for p in processes:
            p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for f in handles:
            f.close()


if __name__ == "__main__":
    with services() as cfg:
        print({"knowledge_http_ready": True, "tickets_http_ready": True}, flush=True)
