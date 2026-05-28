"""API key repository — Postgres veya dosya (JSON) fallback.

Tasarım: API key seti küçük + nadiren değişir → boot'ta bir kez cache'e yüklenir
(auth hot-path'inde async DB sorgusu YOK). DATABASE_URL set ise ApiKey tablosundan
aktif key'ler, değilse API_KEYS_FILE JSON'dan. Her iki yolda da {hash_or_key: label}
dict döner; auth.py `_match_api_key` bunu sabit-zaman + hash-mode ile karşılaştırır.

Revoke/rotate: DB modunda `active=False` veya satır silme → cache refresh.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Protocol

import structlog

log = structlog.get_logger()


class ApiKeyRepo(Protocol):
    """Aktif API key haritasını döndürür: {key_hash_or_plaintext: label}."""

    name: str

    async def list_active(self) -> dict[str, str]: ...


class FilesystemApiKeyRepo:
    """API_KEYS_FILE JSON ({key_or_hash: label}) — eski davranış."""

    name = "filesystem"

    def __init__(self, keys_file: str) -> None:
        self.keys_file = keys_file

    def _read_sync(self) -> dict[str, str]:
        p = Path(self.keys_file)
        if not p.exists():
            log.warning("api_keys_file_missing", path=self.keys_file)
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise TypeError("API_KEYS_FILE must contain a JSON object")
            return {str(k): str(v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            log.error("api_keys_file_invalid", error=str(exc))
            return {}

    async def list_active(self) -> dict[str, str]:
        if not self.keys_file:
            return {}
        # Blocking dosya I/O thread'e — event loop'u bloke etme (ASYNC240).
        return await asyncio.to_thread(self._read_sync)


class PostgresApiKeyRepo:
    """ApiKey tablosundan active=True key'leri {key_hash: label} olarak döndürür."""

    name = "postgres"

    async def list_active(self) -> dict[str, str]:
        from sqlalchemy import select
        from sqlmodel import col

        from db.engine import session_scope
        from db.models import ApiKey

        # col() — SQLModel: alan-seviyesi `bool` tipini SQLAlchemy kolonuna sarar
        # (mypy `ApiKey.active.is_()` görmesin; runtime'da doğru SQL üretir).
        async with session_scope() as session:
            rows = (
                await session.execute(select(ApiKey).where(col(ApiKey.active).is_(True)))
            ).scalars().all()
        return {row.key_hash: row.label for row in rows}


def get_api_key_repo(keys_file: str) -> ApiKeyRepo:
    """env-gated factory — DB açıksa Postgres, değilse JSON dosya."""
    from db.engine import is_db_enabled

    if is_db_enabled():
        return PostgresApiKeyRepo()
    return FilesystemApiKeyRepo(keys_file)
