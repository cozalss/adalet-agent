"""İlişkisel DB katmanı — env-gated (DATABASE_URL).

DATABASE_URL yoksa tüm DB işlevleri no-op / fallback; dev/test/CI Postgres
gerektirmez. Production: postgresql+asyncpg://... (Docker, Hetzner/TR — KVKK).
"""

from db.engine import (
    aclose_engine,
    create_all,
    get_engine,
    get_sessionmaker,
    is_db_enabled,
    reset_engine_for_test,
    session_scope,
)

__all__ = (
    "aclose_engine",
    "create_all",
    "get_engine",
    "get_sessionmaker",
    "is_db_enabled",
    "reset_engine_for_test",
    "session_scope",
)
