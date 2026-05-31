"""Kullanıcı hesabı repository — filesystem + Postgres (SQLite test)."""

from __future__ import annotations

import pytest

from db import engine as db_engine
from db.repositories.users import (
    FilesystemUserRepo,
    PostgresUserRepo,
    get_user_repo,
    normalize_email,
)


@pytest.fixture
def _sqlite_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    db_engine.reset_engine_for_test()
    yield
    db_engine.reset_engine_for_test()
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_normalize_email():
    assert normalize_email("  Ayse@Example.COM ") == "ayse@example.com"


def test_factory(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_engine.reset_engine_for_test()
    assert isinstance(get_user_repo(tmp_path / "u.json"), FilesystemUserRepo)


@pytest.mark.asyncio
async def test_filesystem_create_get(tmp_path):
    repo = FilesystemUserRepo(tmp_path / "u.json")
    assert await repo.get("a@b.com") is None
    assert await repo.create("A@B.com", "hash1", "Ayşe") is True
    got = await repo.get("a@b.com")  # case-insensitive
    assert got["email"] == "a@b.com" and got["name"] == "Ayşe"
    # çift kayıt reddedilir
    assert await repo.create("a@b.com", "hash2", "Başka") is False
    assert (await repo.get("a@b.com"))["password_hash"] == "hash1"  # ezilmedi


@pytest.mark.asyncio
async def test_postgres_create_get(_sqlite_db):
    from db.engine import create_all

    await create_all()
    repo = PostgresUserRepo()
    assert await repo.create("x@y.com", "phash", "Veli") is True
    got = await repo.get("X@Y.com")
    assert got["email"] == "x@y.com" and got["name"] == "Veli"
    assert await repo.create("x@y.com", "other", "Z") is False
