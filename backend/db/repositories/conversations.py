"""Sohbet geçmişi + dosya repository — Postgres veya dosya (JSON) fallback.

env-gated: DATABASE_URL set ise Postgres (Conversation+Message+UploadedFile
tabloları), değilse tek JSON dosyası (dev/test/CI). Çağıran (api/routes/
conversations.py) backend seçimini bilmez.

KVKK (gevşetildi ama temel hijyen korunur): saklama anahtarı = owner_sub_hash
(fingerprint(sub)); ham email saklanmaz. Mesaj içeriği backend'in zaten
PII-mask'ladığı haldedir. Her get/delete owner kontrolüyle IDOR'a kapalı.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import structlog

log = structlog.get_logger()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ----------------------------- Conversations -----------------------------


class ConversationRepo(Protocol):
    """Sohbet geçmişi backend protokolü."""

    name: str

    async def list_for_owner(self, owner: str, q: str | None = None) -> list[dict[str, Any]]: ...
    async def get(self, owner: str, conv_id: str) -> dict[str, Any] | None: ...
    async def upsert(self, owner: str, conv: dict[str, Any]) -> bool: ...
    async def delete(self, owner: str, conv_id: str) -> bool: ...
    async def delete_all(self, owner: str) -> int: ...
    async def list_files(self, owner: str) -> list[dict[str, Any]]: ...
    async def add_file(self, owner: str, meta: dict[str, Any]) -> None: ...


def _summary(conv: dict[str, Any]) -> dict[str, Any]:
    """Liste için hafif metadata (mesaj gövdesi olmadan)."""
    return {
        "id": conv["id"],
        "title": conv.get("title", ""),
        "domain": conv.get("domain", ""),
        "message_count": conv.get("message_count", len(conv.get("messages", []))),
        "created_at": conv.get("created_at", ""),
        "updated_at": conv.get("updated_at", ""),
    }


class FilesystemConversationRepo:
    """Tek JSON dosyası — dev/test fallback. Atomik yazım + thread-lock."""

    name = "filesystem"

    def __init__(self, store_file: Path) -> None:
        self.store_file = store_file
        self.files_file = store_file.with_name("uploaded_files.json")
        self._lock = threading.Lock()

    def _read(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            log.error("conversations_file_invalid", path=str(path), error=str(exc))
            return {}

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    async def list_for_owner(self, owner: str, q: str | None = None) -> list[dict[str, Any]]:
        data = await asyncio.to_thread(self._read, self.store_file)
        convs = list((data.get(owner) or {}).values())
        if q:
            ql = q.lower()
            convs = [c for c in convs if ql in (c.get("title", "") + " " + _haystack(c)).lower()]
        convs.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
        return [_summary(c) for c in convs]

    async def get(self, owner: str, conv_id: str) -> dict[str, Any] | None:
        data = await asyncio.to_thread(self._read, self.store_file)
        return (data.get(owner) or {}).get(conv_id)

    async def upsert(self, owner: str, conv: dict[str, Any]) -> bool:
        def _op() -> bool:
            with self._lock:
                data = self._read(self.store_file)
                bucket = data.setdefault(owner, {})  # owner-scoped → çakışma yok
                prev = bucket.get(conv["id"], {})
                bucket[conv["id"]] = {
                    **conv,
                    "created_at": prev.get("created_at") or conv.get("created_at") or _now_iso(),
                    "updated_at": _now_iso(),
                    "message_count": len(conv.get("messages", [])),
                }
                self._write(self.store_file, data)
                return True

        return await asyncio.to_thread(_op)

    async def delete(self, owner: str, conv_id: str) -> bool:
        def _op() -> bool:
            with self._lock:
                data = self._read(self.store_file)
                bucket = data.get(owner) or {}
                if bucket.pop(conv_id, None) is None:
                    return False
                self._write(self.store_file, data)
                return True

        return await asyncio.to_thread(_op)

    async def delete_all(self, owner: str) -> int:
        def _op() -> int:
            with self._lock:
                data = self._read(self.store_file)
                bucket = data.pop(owner, None) or {}
                if bucket:
                    self._write(self.store_file, data)
                return len(bucket)

        return await asyncio.to_thread(_op)

    async def list_files(self, owner: str) -> list[dict[str, Any]]:
        data = await asyncio.to_thread(self._read, self.files_file)
        raw = data.get(owner)
        items = list(raw) if isinstance(raw, list) else []  # tip-güvenli
        items.sort(key=lambda f: f.get("uploaded_at", ""), reverse=True)
        return items

    async def add_file(self, owner: str, meta: dict[str, Any]) -> None:
        def _op() -> None:
            with self._lock:
                data = self._read(self.files_file)
                data.setdefault(owner, []).append({**meta, "uploaded_at": _now_iso()})
                self._write(self.files_file, data)

        await asyncio.to_thread(_op)


def _haystack(conv: dict[str, Any]) -> str:
    """Arama için mesaj metinlerini birleştir (başlık dışı içerik araması)."""
    return " ".join(m.get("content", "") for m in conv.get("messages", []))


class PostgresConversationRepo:
    """Conversation + Message + UploadedFile tabloları (owner-scoped)."""

    name = "postgres"

    async def list_for_owner(self, owner: str, q: str | None = None) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from sqlmodel import col

        from db.engine import session_scope
        from db.models import Conversation

        stmt = select(Conversation).where(col(Conversation.owner_sub_hash) == owner)
        if q:
            stmt = stmt.where(col(Conversation.title).ilike(f"%{q}%"))
        stmt = stmt.order_by(col(Conversation.updated_at).desc())
        async with session_scope() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id, "title": r.title, "domain": r.domain,
                "message_count": r.message_count,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]

    async def get(self, owner: str, conv_id: str) -> dict[str, Any] | None:
        from sqlalchemy import select
        from sqlmodel import col

        from db.engine import session_scope
        from db.models import Conversation, Message

        async with session_scope() as session:
            conv = await session.get(Conversation, conv_id)
            if conv is None or conv.owner_sub_hash != owner:
                return None  # yok veya başka kullanıcı → IDOR'a kapalı
            msgs = (await session.execute(
                select(Message).where(col(Message.conversation_id) == conv_id)
                .order_by(col(Message.turn_index))
            )).scalars().all()
        return {
            "id": conv.id, "title": conv.title, "domain": conv.domain,
            "message_count": conv.message_count,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "messages": [
                {
                    "turn_index": m.turn_index, "role": m.role, "content": m.content,
                    "domain": m.domain, "citations": m.citations_json, "confidence": m.confidence,
                }
                for m in msgs
            ],
        }

    async def upsert(self, owner: str, conv: dict[str, Any]) -> bool:
        import uuid

        from sqlalchemy import delete as sa_delete
        from sqlmodel import col

        from db.engine import session_scope
        from db.models import Conversation, Message

        messages = conv.get("messages", [])
        async with session_scope() as session:
            row = await session.get(Conversation, conv["id"])
            if row is not None and row.owner_sub_hash != owner:
                return False  # başka kullanıcının kaydı → route 403 döner
            if row is None:
                row = Conversation(id=conv["id"], owner_sub_hash=owner,
                                   created_at=datetime.now(UTC))
                session.add(row)
            row.title = conv.get("title", row.title)
            row.domain = conv.get("domain", row.domain)
            row.message_count = len(messages)
            row.updated_at = datetime.now(UTC)
            # Mesajları tam değiştir (idempotent — frontend tüm sohbeti gönderir).
            await session.execute(
                sa_delete(Message).where(col(Message.conversation_id) == conv["id"])
            )
            for i, m in enumerate(messages):
                session.add(Message(
                    id=uuid.uuid4().hex, conversation_id=conv["id"],
                    turn_index=m.get("turn_index", i), role=m.get("role", "user"),
                    content=m.get("content", ""), domain=m.get("domain", ""),
                    citations_json=m.get("citations", []),
                    confidence=float(m.get("confidence", 0.0)),
                ))
        return True

    async def delete_all(self, owner: str) -> int:
        from sqlalchemy import delete as sa_delete
        from sqlalchemy import select
        from sqlmodel import col

        from db.engine import session_scope
        from db.models import Conversation, Message

        async with session_scope() as session:
            ids = (await session.execute(
                select(col(Conversation.id)).where(col(Conversation.owner_sub_hash) == owner)
            )).scalars().all()
            if ids:
                await session.execute(
                    sa_delete(Message).where(col(Message.conversation_id).in_(ids))
                )
                await session.execute(
                    sa_delete(Conversation).where(col(Conversation.owner_sub_hash) == owner)
                )
        return len(ids)

    async def delete(self, owner: str, conv_id: str) -> bool:
        from sqlalchemy import delete as sa_delete
        from sqlmodel import col

        from db.engine import session_scope
        from db.models import Conversation, Message

        async with session_scope() as session:
            row = await session.get(Conversation, conv_id)
            if row is None or row.owner_sub_hash != owner:
                return False
            await session.execute(
                sa_delete(Message).where(col(Message.conversation_id) == conv_id)
            )
            await session.delete(row)
        return True

    async def list_files(self, owner: str) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from sqlmodel import col

        from db.engine import session_scope
        from db.models import UploadedFile

        async with session_scope() as session:
            rows = (await session.execute(
                select(UploadedFile).where(col(UploadedFile.owner_sub_hash) == owner)
                .order_by(col(UploadedFile.uploaded_at).desc())
            )).scalars().all()
        return [
            {
                "id": r.id, "conversation_id": r.conversation_id, "filename": r.filename,
                "ocr_engine": r.ocr_engine, "n_chars": r.n_chars, "pii_flag": r.pii_flag,
                "uploaded_at": r.uploaded_at.isoformat(),
            }
            for r in rows
        ]

    async def add_file(self, owner: str, meta: dict[str, Any]) -> None:
        import uuid

        from db.engine import session_scope
        from db.models import UploadedFile

        async with session_scope() as session:
            session.add(UploadedFile(
                id=uuid.uuid4().hex, owner_sub_hash=owner,
                conversation_id=meta.get("conversation_id", ""),
                filename=meta.get("filename", ""), ocr_engine=meta.get("ocr_engine", ""),
                n_chars=int(meta.get("n_chars", 0)), pii_flag=bool(meta.get("pii_flag", False)),
            ))


def get_conversation_repo(store_file: Path) -> ConversationRepo:
    """env-gated factory — DB açıksa Postgres, değilse JSON dosya."""
    from db.engine import is_db_enabled

    if is_db_enabled():
        return PostgresConversationRepo()
    return FilesystemConversationRepo(store_file)
