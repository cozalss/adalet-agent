"""W6.1/W6.2 — JWT + API key auth middleware testleri."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware import auth as auth_mod
from api.middleware.auth import (
    Principal,
    authenticate,
    decode_token,
    issue_token,
    reset_api_key_cache,
)


@pytest.fixture
def _auth_env(monkeypatch):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "JWT_SECRET", "test-secret-32bytes-min-OKwhatever")
    monkeypatch.setattr(auth_mod, "JWT_TTL_SECONDS", 3600)
    monkeypatch.setattr(auth_mod, "JWT_ISSUER", "test-iss")
    monkeypatch.setattr(auth_mod, "JWT_AUDIENCE", "test-aud")
    reset_api_key_cache()


@pytest.fixture
def _api_keys_file(tmp_path, monkeypatch):
    p = tmp_path / "keys.json"
    p.write_text(json.dumps({"key-alpha-123": "alpha-corp", "key-beta-456": "beta-ltd"}))
    monkeypatch.setattr(auth_mod, "API_KEYS_FILE", str(p))
    reset_api_key_cache()
    return p


@pytest.fixture
def auth_app(_auth_env, _api_keys_file):
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/private")
    async def private(p: Principal = pytest.importorskip("fastapi").Depends(authenticate)):  # type: ignore[arg-type]
        return {"sub": p.sub, "kind": p.kind, "anonymous": p.anonymous}

    return TestClient(app)


def test_jwt_issue_and_decode_roundtrip(_auth_env):
    tok = issue_token("user-1", role="beta", extra="x")
    claims = decode_token(tok)
    assert claims["sub"] == "user-1"
    assert claims["role"] == "beta"
    assert claims["extra"] == "x"


def test_jwt_expired_token_rejected(monkeypatch, _auth_env):
    monkeypatch.setattr(auth_mod, "JWT_TTL_SECONDS", -10)  # expired
    tok = issue_token("user-2")
    with pytest.raises(Exception) as exc:
        decode_token(tok)
    assert "süre" in str(exc.value).lower() or "expired" in str(exc.value).lower()


def test_jwt_tampered_token_rejected(_auth_env):
    tok = issue_token("user-3")
    tampered = tok[:-4] + "XXXX"
    with pytest.raises(Exception):
        decode_token(tampered)


def test_jwt_invalid_token_detail_is_generic(_auth_env):
    """Geçersiz token 401 detail'i iç JWT sebebini SIZDIRMAMALI (forgery oracle).

    Eskiden detail=f"geçersiz token: {exc}" imza/audience/issuer hatasını
    istemciye veriyordu. Artık generic; spesifik sebep yalnız log'da.
    """
    from fastapi import HTTPException

    tok = issue_token("user-x")
    tampered = tok[:-4] + "XXXX"
    with pytest.raises(HTTPException) as ei:
        decode_token(tampered)
    assert ei.value.status_code == 401
    assert ei.value.detail == "geçersiz veya süresi dolmuş token"
    low = str(ei.value.detail).lower()
    assert "signature" not in low and "audience" not in low and "issuer" not in low


def test_health_public_no_auth_required(auth_app):
    r = auth_app.get("/health")
    assert r.status_code == 200


def test_private_without_auth_returns_401(auth_app):
    r = auth_app.get("/private")
    assert r.status_code == 401


def test_private_with_valid_jwt(auth_app, _auth_env):
    tok = issue_token("alice", role="beta")
    r = auth_app.get("/private", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    body = r.json()
    assert body["sub"] == "alice"
    assert body["kind"] == "user"


def test_private_with_valid_api_key(auth_app):
    r = auth_app.get("/private", headers={"X-API-Key": "key-alpha-123"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "api_key"
    assert body["sub"] == "alpha-corp"


def test_private_with_unknown_api_key_returns_401(auth_app):
    r = auth_app.get("/private", headers={"X-API-Key": "no-such-key"})
    assert r.status_code == 401


def test_match_api_key_constant_time_lookup():
    """_match_api_key doğru label'ı döndürür, yanlış/boş key None.

    Düz dict.get yerine hmac.compare_digest (timing-safe). Davranış aynı kalmalı.
    """
    from api.middleware.auth import _match_api_key

    keys = {"key-alpha-123": "alpha-corp", "key-beta-456": "beta-ltd"}
    assert _match_api_key("key-alpha-123", keys) == "alpha-corp"
    assert _match_api_key("key-beta-456", keys) == "beta-ltd"
    assert _match_api_key("no-such-key", keys) is None
    assert _match_api_key("anything", {}) is None


def test_match_api_key_hashed_mode():
    """SHA-256 hash'li stored key → sağlanan ham key hash'lenip eşleşir (C2).

    Dosya sızsa bile ham key açığa çıkmaz. Yanlış key None döner.
    """
    from api.middleware.auth import _match_api_key, hash_api_key

    raw = "super-secret-b2b-key-2026"
    keys = {hash_api_key(raw): "acme-corp", hash_api_key("other"): "beta-ltd"}
    # Stored değer 64-hex hash → ham key hash'lenip karşılaştırılır
    assert _match_api_key(raw, keys) == "acme-corp"
    assert _match_api_key("other", keys) == "beta-ltd"
    assert _match_api_key("wrong-key", keys) is None
    # hash_api_key deterministik + 64-hex
    assert hash_api_key(raw) == hash_api_key(raw)
    assert len(hash_api_key(raw)) == 64


def test_match_api_key_mixed_hash_and_plaintext():
    """Hash + plaintext karışık dosya — ikisi de çalışır (geriye uyum)."""
    from api.middleware.auth import _match_api_key, hash_api_key

    keys = {hash_api_key("hashed-key"): "hashed-corp", "plain-key": "plain-corp"}
    assert _match_api_key("hashed-key", keys) == "hashed-corp"
    assert _match_api_key("plain-key", keys) == "plain-corp"


def test_auth_disabled_returns_anonymous(monkeypatch):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", False)
    app = FastAPI()

    from fastapi import Depends as _Depends

    @app.get("/private")
    async def private(p: Principal = _Depends(authenticate)):
        return {"kind": p.kind, "anonymous": p.anonymous}

    client = TestClient(app)
    r = client.get("/private")
    assert r.status_code == 200
    assert r.json()["anonymous"] is True
