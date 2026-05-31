"""Kullanıcı hesabı repository — Postgres veya dosya (JSON) fallback.

env-gated: DATABASE_URL set ise UserAccount tablosu, değilse tek JSON dosyası
(dev/test/CI). E-posta PK (normalize: lowercase+strip). Ham şifre saklanmaz —
yalnız password_hash (pbkdf2). create atomik (çift-kayıt yarışını lock önler).
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


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class UserRepo(Protocol):
    name: str

    async def get(self, email: str) -> dict[str, Any] | None: ...
    async def create(self, email: str, password_hash: str, name: str) -> bool: ...


class FilesystemUserRepo:
    """Tek JSON dosyası {email: {...}} — dev/test fallback. Atomik + thread-lock."""

    name = "filesystem"

    def __init__(self, store_file: Path) -> None:
        self.store_file = store_file
        self._lock = threading.Lock()

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.store_file.exists():
            return {}
        try:
            data = json.loads(self.store_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            log.error("users_file_invalid", error=str(exc))
            return {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.store_file)

    async def get(self, email: str) -> dict[str, Any] | None:
        data = await asyncio.to_thread(self._read)
        return data.get(normalize_email(email))

    async def create(self, email: str, password_hash: str, name: str) -> bool:
        key = normalize_email(email)

        def _op() -> bool:
            with self._lock:
                data = self._read()
                if key in data:  # zaten var → çift-kayıt yok
                    return False
                data[key] = {
                    "email": key, "password_hash": password_hash,
                    "name": name, "created_at": _now_iso(),
                }
                self._write(data)
                return True

        return await asyncio.to_thread(_op)


class PostgresUserRepo:
    """UserAccount tablosu (email PK)."""

    name = "postgres"

    async def get(self, email: str) -> dict[str, Any] | None:
        from db.engine import session_scope
        from db.models import UserAccount

        async with session_scope() as session:
            row = await session.get(UserAccount, normalize_email(email))
            if row is None:
                return None
            return {
                "email": row.email, "password_hash": row.password_hash,
                "name": row.name, "created_at": row.created_at.isoformat(),
            }

    async def create(self, email: str, password_hash: str, name: str) -> bool:
        from sqlalchemy.exc import IntegrityError

        from db.engine import session_scope
        from db.models import UserAccount

        key = normalize_email(email)
        try:
            async with session_scope() as session:
                existing = await session.get(UserAccount, key)
                if existing is not None:
                    return False
                session.add(UserAccount(
                    email=key, password_hash=password_hash, name=name,
                    created_at=datetime.now(UTC),
                ))
        except IntegrityError:
            return False  # eşzamanlı çift-kayıt → PK çakışması
        return True


def get_user_repo(store_file: Path) -> UserRepo:
    """env-gated factory — DB açıksa Postgres, değilse JSON dosya."""
    from db.engine import is_db_enabled

    if is_db_enabled():
        return PostgresUserRepo()
    return FilesystemUserRepo(store_file)
