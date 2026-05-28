"""DB katmanı — engine env-gate + feedback repository (Postgres/dosya) testleri.

Container'sız: DATABASE_URL=sqlite+aiosqlite:///:memory: ile gerçek async DB.
Postgres-spesifik tip yok → SQLite dialect testi geçerli (üretim asyncpg).
"""

from __future__ import annotations

import pytest

from db import engine as db_engine
from db.repositories.feedback import (
    FilesystemFeedbackRepo,
    PostgresFeedbackRepo,
    get_feedback_repo,
)


@pytest.fixture
def _sqlite_db(monkeypatch):
    """In-memory async SQLite — gerçek DB ama container'sız."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    db_engine.reset_engine_for_test()
    yield
    db_engine.reset_engine_for_test()
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _record(fid: str = "fb_test_1") -> dict:
    return {
        "feedback_id": fid,
        "principal_kind": "user",
        "principal_sub_hash": "abc123",
        "conversation_id": "conv-1",
        "turn_index": 0,
        "rating": "up",
        "comment_masked": "güzel cevap",
    }


def test_factory_picks_filesystem_when_db_off(tmp_path, monkeypatch):
    """DATABASE_URL yokken factory FilesystemFeedbackRepo döner (fallback)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_engine.reset_engine_for_test()
    repo = get_feedback_repo(tmp_path)
    assert isinstance(repo, FilesystemFeedbackRepo)
    assert not db_engine.is_db_enabled()


def test_factory_picks_postgres_when_db_on(tmp_path, _sqlite_db):
    """DATABASE_URL set → factory PostgresFeedbackRepo (SQLAlchemy backend)."""
    repo = get_feedback_repo(tmp_path)
    assert isinstance(repo, PostgresFeedbackRepo)
    assert db_engine.is_db_enabled()


@pytest.mark.asyncio
async def test_filesystem_repo_writes_jsonl(tmp_path):
    """Dosya repo JSONL satırı yazar (eski davranış korunur)."""
    repo = FilesystemFeedbackRepo(tmp_path)
    await repo.save(_record("fb_fs_1"))
    files = list(tmp_path.glob("feedback_*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "fb_fs_1" in content and "güzel cevap" in content


@pytest.mark.asyncio
async def test_postgres_repo_persists_row(_sqlite_db):
    """Postgres repo (SQLite test) Feedback satırını DB'ye yazar + okunur."""
    from sqlalchemy import select

    from db.engine import create_all, session_scope
    from db.models import Feedback

    await create_all()
    repo = PostgresFeedbackRepo()
    await repo.save(_record("fb_pg_1"))

    async with session_scope() as session:
        rows = (await session.execute(select(Feedback))).scalars().all()
    assert len(rows) == 1
    assert rows[0].feedback_id == "fb_pg_1"
    assert rows[0].rating == "up"
    assert rows[0].principal_sub_hash == "abc123"


@pytest.mark.asyncio
async def test_session_scope_raises_when_db_off(monkeypatch):
    """DB kapalıyken session_scope çağrısı net hata verir (sessiz fail değil)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_engine.reset_engine_for_test()
    with pytest.raises(RuntimeError, match="DB devre dışı"):
        async with db_engine.session_scope():
            pass
