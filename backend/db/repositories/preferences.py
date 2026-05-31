"""Kullanıcı tercihi repository — Postgres veya dosya (JSON) fallback.

env-gated: DATABASE_URL set ise PostgresPreferenceRepo (kalıcı, cihazlar-arası),
değilse FilesystemPreferenceRepo (tek JSON dosyası — dev/test/CI).

Çağıran (api/routes/preferences.py) `get_preference_repo(path).get/upsert/delete`
kullanır; backend seçimi şeffaf.

KVKK: saklama anahtarı = fingerprint(principal.sub) (ham email değil). Yalnız
hassas-OLMAYAN UI tercihleri. Anonim kullanıcı bu katmana hiç ulaşmaz (route 401).
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


class PreferenceRepo(Protocol):
    """Tüm tercih backend'leri bu protokole uyar."""

    name: str

    async def get(self, sub_hash: str) -> dict[str, Any] | None: ...
    async def upsert(self, sub_hash: str, prefs: dict[str, Any]) -> None: ...
    async def delete(self, sub_hash: str) -> None: ...


class FilesystemPreferenceRepo:
    """Tek JSON dosyası {sub_hash: prefs} — dev/test fallback.

    Atomik yazım: tmp dosyaya yaz + replace (yarım yazımda bozulma yok).
    """

    name = "filesystem"

    def __init__(self, store_file: Path) -> None:
        self.store_file = store_file
        # Eşzamanlı upsert/delete read-modify-write yarışını önle (biri diğerinin
        # yazımını ezmesin). to_thread worker'ları arasında paylaşılan kilit.
        self._lock = threading.Lock()

    def _read_all(self) -> dict[str, dict[str, Any]]:
        p = self.store_file
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            log.error("prefs_file_invalid", error=str(exc))
            return {}

    def _write_all(self, data: dict[str, dict[str, Any]]) -> None:
        self.store_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.store_file)

    async def get(self, sub_hash: str) -> dict[str, Any] | None:
        data = await asyncio.to_thread(self._read_all)
        return data.get(sub_hash)

    async def upsert(self, sub_hash: str, prefs: dict[str, Any]) -> None:
        def _op() -> None:
            with self._lock:
                data = self._read_all()
                data[sub_hash] = {**prefs, "updated_at": _now_iso()}
                self._write_all(data)

        await asyncio.to_thread(_op)

    async def delete(self, sub_hash: str) -> None:
        def _op() -> None:
            with self._lock:
                data = self._read_all()
                if data.pop(sub_hash, None) is not None:
                    self._write_all(data)

        await asyncio.to_thread(_op)


class PostgresPreferenceRepo:
    """UserPreference tablosu — PK = sub_hash, satır başına bir kullanıcı (upsert)."""

    name = "postgres"

    async def get(self, sub_hash: str) -> dict[str, Any] | None:
        from db.engine import session_scope
        from db.models import UserPreference

        async with session_scope() as session:
            row = await session.get(UserPreference, sub_hash)
            if row is None:
                return None
            return {
                "display_name": row.display_name,
                "text_scale": row.text_scale,
                "reduce_motion": row.reduce_motion,
                "high_contrast": row.high_contrast,
                "preferred_domains": list(row.preferred_domains or []),
                "updated_at": row.updated_at.isoformat(),
            }

    async def upsert(self, sub_hash: str, prefs: dict[str, Any]) -> None:
        from db.engine import session_scope
        from db.models import UserPreference

        async with session_scope() as session:
            row = await session.get(UserPreference, sub_hash)
            if row is None:
                row = UserPreference(sub_hash=sub_hash)
                session.add(row)
            row.display_name = prefs.get("display_name", row.display_name)
            row.text_scale = prefs.get("text_scale", row.text_scale)
            row.reduce_motion = bool(prefs.get("reduce_motion", row.reduce_motion))
            row.high_contrast = bool(prefs.get("high_contrast", row.high_contrast))
            row.preferred_domains = list(
                prefs.get("preferred_domains", row.preferred_domains)
            )
            row.updated_at = datetime.now(UTC)
            # session_scope commit eder; in-session değişiklik dirty-track edilir.

    async def delete(self, sub_hash: str) -> None:
        from db.engine import session_scope
        from db.models import UserPreference

        async with session_scope() as session:
            row = await session.get(UserPreference, sub_hash)
            if row is not None:
                await session.delete(row)


def get_preference_repo(store_file: Path) -> PreferenceRepo:
    """env-gated factory — DB açıksa Postgres, değilse JSON dosya."""
    from db.engine import is_db_enabled

    if is_db_enabled():
        return PostgresPreferenceRepo()
    return FilesystemPreferenceRepo(store_file)
