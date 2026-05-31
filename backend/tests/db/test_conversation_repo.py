"""Sohbet geçmişi repository — filesystem + Postgres (SQLite test) testleri."""

from __future__ import annotations

import pytest

from db import engine as db_engine
from db.repositories.conversations import (
    FilesystemConversationRepo,
    PostgresConversationRepo,
    get_conversation_repo,
)


@pytest.fixture
def _sqlite_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    db_engine.reset_engine_for_test()
    yield
    db_engine.reset_engine_for_test()
    monkeypatch.delenv("DATABASE_URL", raising=False)


def _conv(cid: str = "conv1", title: str = "Kira sorunu") -> dict:
    return {
        "id": cid, "title": title, "domain": "kira",
        "messages": [
            {"turn_index": 0, "role": "user", "content": "Ev sahibim zam istiyor"},
            {"turn_index": 1, "role": "assistant", "content": "Yasal sınır TÜFE'dir",
             "citations": [{"id": 1, "title": "TBK m.344"}], "confidence": 88.0},
        ],
    }


def test_factory_filesystem_when_db_off(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_engine.reset_engine_for_test()
    assert isinstance(get_conversation_repo(tmp_path / "c.json"), FilesystemConversationRepo)


def test_factory_postgres_when_db_on(tmp_path, _sqlite_db):
    assert isinstance(get_conversation_repo(tmp_path / "c.json"), PostgresConversationRepo)


@pytest.mark.asyncio
async def test_filesystem_roundtrip(tmp_path):
    repo = FilesystemConversationRepo(tmp_path / "c.json")
    assert await repo.list_for_owner("u1") == []

    await repo.upsert("u1", _conv())
    lst = await repo.list_for_owner("u1")
    assert len(lst) == 1
    assert lst[0]["title"] == "Kira sorunu"
    assert lst[0]["message_count"] == 2

    full = await repo.get("u1", "conv1")
    assert full is not None
    assert len(full["messages"]) == 2
    assert full["messages"][1]["citations"][0]["title"] == "TBK m.344"

    assert await repo.delete("u1", "conv1") is True
    assert await repo.get("u1", "conv1") is None
    assert await repo.delete("u1", "conv1") is False  # yok


@pytest.mark.asyncio
async def test_filesystem_owner_isolation(tmp_path):
    """Bir kullanıcı başkasının sohbetini göremez/silemez (IDOR)."""
    repo = FilesystemConversationRepo(tmp_path / "c.json")
    await repo.upsert("u1", _conv("c1"))
    await repo.upsert("u2", _conv("c2"))
    assert await repo.get("u2", "c1") is None  # u2, u1'in sohbetini göremez
    assert await repo.delete("u2", "c1") is False
    assert len(await repo.list_for_owner("u1")) == 1
    assert len(await repo.list_for_owner("u2")) == 1


@pytest.mark.asyncio
async def test_filesystem_search(tmp_path):
    repo = FilesystemConversationRepo(tmp_path / "c.json")
    await repo.upsert("u1", _conv("c1", "Kira artışı"))
    await repo.upsert("u1", _conv("c2", "İşten çıkarılma"))
    res = await repo.list_for_owner("u1", q="kira")
    assert len(res) == 1 and res[0]["id"] == "c1"
    # içerik araması (mesaj metni)
    assert len(await repo.list_for_owner("u1", q="çıkarıl")) == 1


@pytest.mark.asyncio
async def test_filesystem_delete_all(tmp_path):
    repo = FilesystemConversationRepo(tmp_path / "c.json")
    await repo.upsert("u1", _conv("c1"))
    await repo.upsert("u1", _conv("c2"))
    await repo.upsert("u2", _conv("c3"))
    assert await repo.delete_all("u1") == 2
    assert await repo.list_for_owner("u1") == []
    assert len(await repo.list_for_owner("u2")) == 1  # u2 etkilenmez


@pytest.mark.asyncio
async def test_filesystem_files(tmp_path):
    repo = FilesystemConversationRepo(tmp_path / "c.json")
    await repo.add_file("u1", {"filename": "kira.pdf", "n_chars": 1200, "pii_flag": True})
    files = await repo.list_files("u1")
    assert len(files) == 1 and files[0]["filename"] == "kira.pdf" and files[0]["pii_flag"] is True
    assert await repo.list_files("u2") == []  # owner-scoped


@pytest.mark.asyncio
async def test_postgres_roundtrip(_sqlite_db):
    from db.engine import create_all

    await create_all()
    repo = PostgresConversationRepo()

    await repo.upsert("u1", _conv())
    lst = await repo.list_for_owner("u1")
    assert len(lst) == 1 and lst[0]["message_count"] == 2

    full = await repo.get("u1", "conv1")
    assert full["messages"][1]["confidence"] == 88.0
    assert full["messages"][1]["citations"][0]["title"] == "TBK m.344"

    # ikinci upsert = mesajları değiştir (idempotent, çoğaltma yok)
    await repo.upsert("u1", {**_conv(), "title": "Güncellendi"})
    lst2 = await repo.list_for_owner("u1")
    assert len(lst2) == 1 and lst2[0]["title"] == "Güncellendi"
    assert (await repo.get("u1", "conv1"))["message_count"] == 2

    assert await repo.get("u2", "conv1") is None  # IDOR
    # başka kullanıcı aynı conv_id'ye upsert → False (route 403 döner)
    assert await repo.upsert("u2", {**_conv(), "title": "ele geçir"}) is False
    assert (await repo.get("u1", "conv1"))["title"] == "Güncellendi"  # bozulmadı
    assert await repo.delete("u1", "conv1") is True
    assert await repo.get("u1", "conv1") is None


@pytest.mark.asyncio
async def test_postgres_files(_sqlite_db):
    from db.engine import create_all

    await create_all()
    repo = PostgresConversationRepo()
    await repo.add_file("u1", {"filename": "belge.png", "ocr_engine": "tesseract", "n_chars": 500})
    files = await repo.list_files("u1")
    assert len(files) == 1 and files[0]["ocr_engine"] == "tesseract"
    assert await repo.list_files("u2") == []
