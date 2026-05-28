"""API key repository — DB (aktif/revoke) + dosya fallback + cache refresh testleri."""

from __future__ import annotations

import json

import pytest

from db import engine as db_engine
from db.repositories.api_key import (
    FilesystemApiKeyRepo,
    PostgresApiKeyRepo,
    get_api_key_repo,
)


@pytest.fixture
def _sqlite_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    db_engine.reset_engine_for_test()
    yield
    db_engine.reset_engine_for_test()
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_factory_db_off_returns_filesystem(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_engine.reset_engine_for_test()
    assert isinstance(get_api_key_repo(str(tmp_path / "k.json")), FilesystemApiKeyRepo)


def test_factory_db_on_returns_postgres(_sqlite_db):
    assert isinstance(get_api_key_repo(""), PostgresApiKeyRepo)


@pytest.mark.asyncio
async def test_filesystem_repo_reads_json(tmp_path):
    p = tmp_path / "keys.json"
    p.write_text(json.dumps({"hash-a": "alpha", "hash-b": "beta"}), encoding="utf-8")
    repo = FilesystemApiKeyRepo(str(p))
    keys = await repo.list_active()
    assert keys == {"hash-a": "alpha", "hash-b": "beta"}


@pytest.mark.asyncio
async def test_filesystem_repo_missing_file_empty(tmp_path):
    repo = FilesystemApiKeyRepo(str(tmp_path / "yok.json"))
    assert await repo.list_active() == {}


@pytest.mark.asyncio
async def test_postgres_repo_only_active(_sqlite_db):
    """DB modunda yalnız active=True key'ler döner (revoke = active False)."""
    from db.engine import create_all, session_scope
    from db.models import ApiKey

    await create_all()
    async with session_scope() as s:
        s.add(ApiKey(key_hash="h-active", label="acme", active=True))
        s.add(ApiKey(key_hash="h-revoked", label="eski", active=False))

    repo = PostgresApiKeyRepo()
    keys = await repo.list_active()
    assert keys == {"h-active": "acme"}   # revoked dahil değil


@pytest.mark.asyncio
async def test_refresh_api_key_cache_from_db(_sqlite_db):
    """auth.refresh_api_key_cache DB'den cache'i doldurur + _match_api_key çalışır."""
    from api.middleware import auth as auth_mod
    from db.engine import create_all, session_scope
    from db.models import ApiKey

    await create_all()
    raw = "b2b-prod-key-2026"
    async with session_scope() as s:
        s.add(ApiKey(key_hash=auth_mod.hash_api_key(raw), label="acme-corp", active=True))

    await auth_mod.refresh_api_key_cache()
    keys = auth_mod.get_api_keys()
    assert auth_mod._match_api_key(raw, keys) == "acme-corp"
    assert auth_mod._match_api_key("yanlis", keys) is None
    auth_mod.reset_api_key_cache()
