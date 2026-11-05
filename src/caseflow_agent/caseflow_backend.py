"""Real HTTP/PostgreSQL services; knowledge models/chunking reuse Notebook.

This module is a task-owned extension. The pinned upstream files stay pristine.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
import sys
import uuid

from fastapi import FastAPI, Header, HTTPException, Request
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from .common import ROOT, digest

sys.path.insert(0, str(ROOT / "upstream/notebook"))
from apps.api.app.models.base import Base
from apps.api.app.models.knowledge import (
    KnowledgeBlock,
    KnowledgeVersion,
    KnowledgeChunk,
)
from apps.api.app.services.chunking import chunk_markdown


def create_app(role=None, url=None, token=None):
    role = role or os.environ["CASEFLOW_ROLE"]
    url = url or os.environ["CASEFLOW_DATABASE_URL"]
    token = token or os.environ["CASEFLOW_INTERNAL_TOKEN"]
    engine = create_async_engine(url, pool_size=5)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def index_one(operation_id):
        async with Session.begin() as s:
            r = (
                (
                    await s.execute(
                        text(
                            "SELECT * FROM outcomes_receipts WHERE operation_id=:op FOR UPDATE"
                        ),
                        {"op": operation_id},
                    )
                )
                .mappings()
                .first()
            )
            if not r or r["state"] != "index_pending":
                return
            kb = await s.get(KnowledgeBlock, r["knowledge_id"], with_for_update=True)
            version = await s.get(KnowledgeVersion, r["version_id"])
            if kb.current_version_id != version.id:
                await s.execute(
                    text(
                        "UPDATE outcomes_receipts SET state='superseded' WHERE operation_id=:op"
                    ),
                    {"op": operation_id},
                )
                return
            await s.execute(
                update(KnowledgeChunk)
                .where(KnowledgeChunk.knowledge_block_id == kb.id)
                .values(is_active=False)
            )
            for draft in chunk_markdown(version.markdown_content):
                s.add(
                    KnowledgeChunk(
                        knowledge_block_id=kb.id,
                        knowledge_version_id=version.id,
                        chunk_index=draft.chunk_index,
                        heading_path=draft.heading_path,
                        content=draft.content,
                        token_count=draft.token_count,
                        char_start=draft.char_start,
                        char_end=draft.char_end,
                        content_hash=draft.content_hash,
                        is_active=True,
                    )
                )
            kb.status = "searchable"
            await s.execute(
                text(
                    "UPDATE outcomes_receipts SET state='ready' WHERE operation_id=:op"
                ),
                {"op": operation_id},
            )

    async def worker():
        while True:
            try:
                async with engine.connect() as c:
                    paused = (
                        await c.execute(
                            text(
                                "SELECT value FROM outcomes_control WHERE key='pause_index'"
                            )
                        )
                    ).scalar()
                    ops = (
                        []
                        if paused == "1"
                        else (
                            await c.execute(
                                text(
                                    "SELECT operation_id FROM outcomes_receipts WHERE state='index_pending' ORDER BY operation_id LIMIT 10"
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                for op in ops:
                    await index_one(op)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Retry the durable pending job; do not claim ready on exceptions.
                await asyncio.sleep(0.5)
            await asyncio.sleep(0.1)

    @asynccontextmanager
    async def lifespan(app):
        async with engine.begin() as c:
            if role == "knowledge":
                await c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await c.run_sync(Base.metadata.create_all)
                await c.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS outcomes_scopes(knowledge_id UUID PRIMARY KEY,scope TEXT NOT NULL)"
                    )
                )
                await c.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS outcomes_receipts(operation_id TEXT PRIMARY KEY,payload_hash TEXT NOT NULL,knowledge_id UUID NOT NULL,version_id UUID NOT NULL,version_number INT NOT NULL,state TEXT NOT NULL)"
                    )
                )
                await c.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS outcomes_control(key TEXT PRIMARY KEY,value TEXT)"
                    )
                )
                await c.execute(
                    text(
                        "INSERT INTO outcomes_control VALUES('pause_index','0') ON CONFLICT DO NOTHING"
                    )
                )
            else:
                await c.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY,scope TEXT NOT NULL,status TEXT NOT NULL,version INT NOT NULL,knowledge_id TEXT NOT NULL,knowledge_version INT,title TEXT NOT NULL,description TEXT NOT NULL)"
                    )
                )
                await c.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS ticket_receipts(operation_id TEXT PRIMARY KEY,payload_hash TEXT NOT NULL,ticket_id TEXT NOT NULL,version INT NOT NULL,result JSONB NOT NULL)"
                    )
                )
        job = asyncio.create_task(worker()) if role == "knowledge" else None
        yield
        if job:
            job.cancel()
            try:
                await job
            except asyncio.CancelledError:
                pass
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def internal_auth(request: Request, call_next):
        if (
            request.url.path != "/health"
            and request.headers.get("x-internal-token") != token
        ):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {"error": "unauthorized_internal_call"}, status_code=403
            )
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"ok": True, "service": role}

    async def kb_snapshot(s, key):
        try:
            key = uuid.UUID(key)
        except ValueError:
            raise HTTPException(404, "knowledge_not_found")
        kb = await s.get(KnowledgeBlock, key)
        if not kb:
            raise HTTPException(404, "knowledge_not_found")
        v = await s.get(KnowledgeVersion, kb.current_version_id)
        scope = (
            await s.execute(
                text("SELECT scope FROM outcomes_scopes WHERE knowledge_id=:k"),
                {"k": key},
            )
        ).scalar()
        indexed = (
            await s.execute(
                select(KnowledgeChunk.knowledge_version_id)
                .where(
                    KnowledgeChunk.knowledge_block_id == key,
                    KnowledgeChunk.is_active.is_(True),
                )
                .limit(1)
            )
        ).scalar()
        iv = await s.get(KnowledgeVersion, indexed) if indexed else None
        return {
            "id": str(key),
            "scope": scope,
            "title": kb.title,
            "content": v.markdown_content,
            "version": v.version_number,
            "content_hash": v.content_hash,
            "status": kb.status,
            "indexed_version": iv.version_number if iv else None,
        }

    if role == "knowledge":

        @app.post("/seed")
        async def seed(payload: dict):
            key = uuid.UUID(payload["id"])
            async with Session.begin() as s:
                if await s.get(KnowledgeBlock, key):
                    raise HTTPException(409, "fixture_already_exists")
                kb = KnowledgeBlock(
                    id=key,
                    title=payload["title"],
                    status="indexing",
                    source_type="manual",
                )
                s.add(kb)
                await s.flush()
                v = KnowledgeVersion(
                    id=uuid.uuid4(),
                    knowledge_block_id=key,
                    version_number=1,
                    version_type="user_confirmed",
                    markdown_content=payload["content"],
                    content_hash=digest(payload["content"].encode()),
                    created_by="user",
                    structured_metadata={},
                )
                s.add(v)
                await s.flush()
                kb.current_version_id = v.id
                await s.execute(
                    text("INSERT INTO outcomes_scopes VALUES(:k,:scope)"),
                    {"k": key, "scope": payload["scope"]},
                )
                await s.execute(
                    text(
                        "INSERT INTO outcomes_receipts VALUES(:op,:hash,:k,:v,1,'index_pending')"
                    ),
                    {
                        "op": "seed-" + str(key),
                        "hash": digest(payload),
                        "k": key,
                        "v": v.id,
                    },
                )
            await index_one("seed-" + str(key))
            async with Session() as s:
                return await kb_snapshot(s, str(key))

        @app.get("/items/{key}")
        async def get_item(key: str):
            async with Session() as s:
                return await kb_snapshot(s, key)

        @app.get("/items")
        async def search(scope: str, q: str = ""):
            async with Session() as s:
                keys = (
                    (
                        await s.execute(
                            text(
                                "SELECT knowledge_id FROM outcomes_scopes WHERE scope=:s LIMIT 30"
                            ),
                            {"s": scope},
                        )
                    )
                    .scalars()
                    .all()
                )
                rows = [await kb_snapshot(s, str(k)) for k in keys]
                return [
                    r
                    for r in rows
                    if not q or q.lower() in (r["title"] + r["content"]).lower()
                ]

        @app.post("/apply")
        async def apply(payload: dict):
            op, key = payload["operation_id"], uuid.UUID(payload["knowledge_id"])
            ph = digest(payload)
            async with Session.begin() as s:
                await s.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:op))"), {"op": op}
                )
                existing = (
                    (
                        await s.execute(
                            text(
                                "SELECT * FROM outcomes_receipts WHERE operation_id=:op"
                            ),
                            {"op": op},
                        )
                    )
                    .mappings()
                    .first()
                )
                if existing:
                    if existing["payload_hash"] != ph:
                        raise HTTPException(409, "idempotency_payload_conflict")
                    return {
                        k: str(v) if isinstance(v, uuid.UUID) else v
                        for k, v in existing.items()
                    }
                kb = await s.get(KnowledgeBlock, key, with_for_update=True)
                if not kb:
                    raise HTTPException(404, "knowledge_not_found")
                scope = (
                    await s.execute(
                        text("SELECT scope FROM outcomes_scopes WHERE knowledge_id=:k"),
                        {"k": key},
                    )
                ).scalar()
                if scope != payload["scope"]:
                    raise HTTPException(403, "scope_denied")
                old = await s.get(KnowledgeVersion, kb.current_version_id)
                if old.version_number != payload["expected_version"]:
                    raise HTTPException(409, "knowledge_version_conflict")
                if not payload.get("content", "").strip():
                    raise HTTPException(422, "empty_content")
                version = KnowledgeVersion(
                    id=uuid.uuid4(),
                    knowledge_block_id=key,
                    version_number=old.version_number + 1,
                    version_type="user_confirmed",
                    markdown_content=payload["content"],
                    content_hash=digest(payload["content"].encode()),
                    created_by="system",
                    structured_metadata={
                        "operation_id": op,
                        "approval_digest": payload["approval_digest"],
                        "source_version_id": str(old.id),
                    },
                )
                s.add(version)
                await s.flush()
                kb.current_version_id = version.id
                kb.status = "indexing"
                await s.execute(
                    text(
                        "INSERT INTO outcomes_receipts VALUES(:op,:hash,:k,:v,:number,'index_pending')"
                    ),
                    {
                        "op": op,
                        "hash": ph,
                        "k": key,
                        "v": version.id,
                        "number": version.version_number,
                    },
                )
                return {
                    "operation_id": op,
                    "version_number": version.version_number,
                    "state": "index_pending",
                    "payload_hash": ph,
                }

        @app.get("/receipts/{op}")
        async def receipt(op: str):
            async with Session() as s:
                r = (
                    (
                        await s.execute(
                            text(
                                "SELECT * FROM outcomes_receipts WHERE operation_id=:op"
                            ),
                            {"op": op},
                        )
                    )
                    .mappings()
                    .first()
                )
                if not r:
                    raise HTTPException(404, "receipt_not_found")
                return {
                    k: str(v) if isinstance(v, uuid.UUID) else v for k, v in r.items()
                }

        @app.post("/control/index")
        async def index_control(payload: dict):
            async with engine.begin() as c:
                await c.execute(
                    text(
                        "UPDATE outcomes_control SET value=:v WHERE key='pause_index'"
                    ),
                    {"v": "1" if payload["paused"] else "0"},
                )
            return {"paused": payload["paused"]}
    else:

        @app.post("/seed")
        async def seed_ticket(payload: dict):
            async with engine.begin() as c:
                await c.execute(
                    text(
                        "INSERT INTO tickets VALUES(:id,:scope,'open',1,:knowledge_id,1,:title,:description)"
                    ),
                    payload,
                )
            return payload

        @app.get("/items/{key}")
        async def get_ticket(key: str):
            async with engine.connect() as c:
                row = (
                    (
                        await c.execute(
                            text("SELECT * FROM tickets WHERE id=:id"), {"id": key}
                        )
                    )
                    .mappings()
                    .first()
                )
                if not row:
                    raise HTTPException(404, "ticket_not_found")
                return dict(row)

        @app.get("/items")
        async def find_tickets(scope: str, q: str = ""):
            async with engine.connect() as c:
                rows = (
                    (
                        await c.execute(
                            text(
                                "SELECT * FROM tickets WHERE scope=:s ORDER BY id LIMIT 100"
                            ),
                            {"s": scope},
                        )
                    )
                    .mappings()
                    .all()
                )
                return [
                    dict(r)
                    for r in rows
                    if not q or q.lower() in (r["title"] + r["description"]).lower()
                ]

        @app.post("/apply")
        async def apply_ticket(payload: dict):
            op = payload["operation_id"]
            ph = digest(payload)
            async with engine.begin() as c:
                await c.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:op))"), {"op": op}
                )
                existing = (
                    (
                        await c.execute(
                            text(
                                "SELECT * FROM ticket_receipts WHERE operation_id=:op"
                            ),
                            {"op": op},
                        )
                    )
                    .mappings()
                    .first()
                )
                if existing:
                    if existing["payload_hash"] != ph:
                        raise HTTPException(409, "idempotency_payload_conflict")
                    return dict(existing["result"])
                old = (
                    (
                        await c.execute(
                            text("SELECT * FROM tickets WHERE id=:id FOR UPDATE"),
                            {"id": payload["ticket_id"]},
                        )
                    )
                    .mappings()
                    .first()
                )
                if not old:
                    raise HTTPException(404, "ticket_not_found")
                if old["scope"] != payload["scope"]:
                    raise HTTPException(403, "scope_denied")
                if old["version"] != payload["expected_version"]:
                    raise HTTPException(409, "ticket_version_conflict")
                if old["knowledge_id"] != payload["knowledge_id"]:
                    raise HTTPException(409, "knowledge_link_conflict")
                result = dict(
                    old,
                    status=payload.get("status", "closed"),
                    version=old["version"] + 1,
                    knowledge_version=payload["knowledge_version"],
                )
                await c.execute(
                    text(
                        "UPDATE tickets SET status=:status,version=:version,knowledge_version=:knowledge_version WHERE id=:id"
                    ),
                    result,
                )
                await c.execute(
                    text(
                        "INSERT INTO ticket_receipts VALUES(:op,:hash,:id,:v,CAST(:result AS JSONB))"
                    ),
                    {
                        "op": op,
                        "hash": ph,
                        "id": old["id"],
                        "v": result["version"],
                        "result": json.dumps(result),
                    },
                )
                return result

    return app


def main():
    import uvicorn

    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=int(os.environ["CASEFLOW_PORT"]),
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
