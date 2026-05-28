"""Async SQLAlchemy/SQLModel engine — env-gated.

`DATABASE_URL` set EDİLMEMİŞSE DB katmanı devre dışı (`is_db_enabled()` False) →
çağıran kod dosya-tabanlı fallback'e düşer. Bu sayede dev/test/CI Postgres
gerektirmez; production `DATABASE_URL=postgresql+asyncpg://...` ile açar.

KVKK: production'da Postgres Docker'da, Hetzner (TR) içinde — bulut DB yok.

Test: `DATABASE_URL=sqlite+aiosqlite:///:memory:` ile container'sız repo testi.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog

log = structlog.get_logger()

_engine: Any = None
_sessionmaker: Any = None


def is_db_enabled() -> bool:
    """DATABASE_URL set ise DB aktif. Dinamik okunur (test monkeypatch-friendly)."""
    return bool(os.getenv("DATABASE_URL", "").strip())


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def get_engine() -> Any:
    """Process-singleton async engine. DB kapalıysa None."""
    global _engine
    if not is_db_enabled():
        return None
    if _engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine
        url = _database_url()
        # SQLite in-memory test'te connection-per-session paylaşımı için
        # StaticPool gerekir; Postgres'te normal pool.
        kwargs: dict[str, Any] = {"echo": False, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            from sqlalchemy.pool import StaticPool
            kwargs = {"echo": False, "poolclass": StaticPool,
                      "connect_args": {"check_same_thread": False}}
        _engine = create_async_engine(url, **kwargs)
        log.info("db_engine_created", dialect=url.split(":", 1)[0])
    return _engine


def get_sessionmaker() -> Any:
    """async_sessionmaker singleton. DB kapalıysa None."""
    global _sessionmaker
    if not is_db_enabled():
        return None
    if _sessionmaker is None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        _sessionmaker = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False,
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[Any]:
    """Transaction-scoped AsyncSession context manager.

    Başarıda commit, hatada rollback, her durumda close. DB kapalıyken
    çağrılmamalı (repository factory bunu DB-on iken kullanır).
    """
    sm = get_sessionmaker()
    if sm is None:
        raise RuntimeError("DB devre dışı (DATABASE_URL yok) — session_scope çağrılamaz")
    session = sm()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def create_all() -> None:
    """Tüm SQLModel tablolarını oluştur (dev/test bootstrap — prod'da Alembic).

    Idempotent (checkfirst). Production migration için `alembic upgrade head`
    tercih edilir; bu yardımcı test/dev hızlı kurulum içindir.
    """
    eng = get_engine()
    if eng is None:
        return
    from sqlmodel import SQLModel

    from db import models  # noqa: F401 — tabloları metadata'ya kaydet

    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def aclose_engine() -> None:
    """Engine dispose — app shutdown'da çağrılır."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


def reset_engine_for_test() -> None:
    """Test yardımcısı — singleton'ları sıfırla (env değişince yeni engine)."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None
