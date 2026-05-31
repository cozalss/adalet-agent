"""Kullanıcı tercihi repository — filesystem + Postgres (SQLite test) testleri.

Container'sız: DATABASE_URL=sqlite+aiosqlite:///:memory: ile gerçek async DB.
"""

from __future__ import annotations

import pytest

from db import engine as db_engine
from db.repositories.preferences import (
    FilesystemPreferenceRepo,
    PostgresPreferenceRepo,
    get_preference_repo,
)


@pytest.fixture
def _sqlite_db(monkeypatch):
    """In-memory async SQLite — gerçek DB ama container'sız."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    db_engine.reset_engine_for_test()
    yield
    db_engine.reset_engine_for_test()
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _prefs() -> dict:
    return {
        "display_name": "Ayşe Yılmaz",
        "text_scale": "large",
        "reduce_motion": True,
        "high_contrast": False,
        "preferred_domains": ["kira", "isHukuku"],
    }


def test_factory_picks_filesystem_when_db_off(tmp_path, monkeypatch):
    """DATABASE_URL yokken factory FilesystemPreferenceRepo döner (fallback)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_engine.reset_engine_for_test()
    repo = get_preference_repo(tmp_path / "prefs.json")
    assert isinstance(repo, FilesystemPreferenceRepo)


def test_factory_picks_postgres_when_db_on(tmp_path, _sqlite_db):
    """DATABASE_URL set → factory PostgresPreferenceRepo."""
    repo = get_preference_repo(tmp_path / "prefs.json")
    assert isinstance(repo, PostgresPreferenceRepo)


@pytest.mark.asyncio
async def test_filesystem_roundtrip(tmp_path):
    """Dosya repo: yaz → oku → güncelle → sil."""
    store = tmp_path / "prefs.json"
    repo = FilesystemPreferenceRepo(store)

    assert await repo.get("user-a") is None

    await repo.upsert("user-a", _prefs())
    got = await repo.get("user-a")
    assert got is not None
    assert got["display_name"] == "Ayşe Yılmaz"
    assert got["text_scale"] == "large"
    assert got["preferred_domains"] == ["kira", "isHukuku"]
    assert "updated_at" in got  # upsert zaman damgası ekler

    # Güncelleme aynı anahtarı ezer (tek satır/kullanıcı).
    await repo.upsert("user-a", {**_prefs(), "text_scale": "compact"})
    assert (await repo.get("user-a"))["text_scale"] == "compact"

    await repo.delete("user-a")
    assert await repo.get("user-a") is None


@pytest.mark.asyncio
async def test_filesystem_isolates_users(tmp_path):
    """Farklı sub_hash'ler birbirini etkilemez (anahtar başına satır)."""
    repo = FilesystemPreferenceRepo(tmp_path / "prefs.json")
    await repo.upsert("user-a", {**_prefs(), "text_scale": "large"})
    await repo.upsert("user-b", {**_prefs(), "text_scale": "compact"})
    assert (await repo.get("user-a"))["text_scale"] == "large"
    assert (await repo.get("user-b"))["text_scale"] == "compact"
    await repo.delete("user-a")
    assert await repo.get("user-a") is None
    assert await repo.get("user-b") is not None  # b silinmez


@pytest.mark.asyncio
async def test_postgres_roundtrip(_sqlite_db):
    """Postgres repo (SQLite test): upsert → get → tekrar upsert → delete."""
    from db.engine import create_all

    await create_all()
    repo = PostgresPreferenceRepo()

    await repo.upsert("hash-1", _prefs())
    got = await repo.get("hash-1")
    assert got is not None
    assert got["display_name"] == "Ayşe Yılmaz"
    assert got["reduce_motion"] is True
    assert got["preferred_domains"] == ["kira", "isHukuku"]

    # İkinci upsert = update (yeni satır eklemez).
    await repo.upsert("hash-1", {**_prefs(), "high_contrast": True})
    got2 = await repo.get("hash-1")
    assert got2["high_contrast"] is True

    await repo.delete("hash-1")
    assert await repo.get("hash-1") is None
