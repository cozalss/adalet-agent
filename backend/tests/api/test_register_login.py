"""/auth/register + /auth/login + /auth/me (e-posta/şifre) testleri."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.middleware import auth as auth_mod
from api.middleware.auth import reset_api_key_cache
from api.routes import auth as auth_route


@pytest.fixture
def _auth_env(monkeypatch):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "AUTH_PROVIDER", "internal")  # internal HS256 yolu (Supabase JWKS değil)
    monkeypatch.setattr(auth_mod, "SUPABASE_URL", "")
    monkeypatch.setattr(auth_mod, "JWT_SECRET", "test-secret-32bytes-min-OK-123456")
    monkeypatch.setattr(auth_mod, "JWT_TTL_SECONDS", 3600)
    monkeypatch.setattr(auth_mod, "JWT_ISSUER", "test-iss")
    monkeypatch.setattr(auth_mod, "JWT_AUDIENCE", "test-aud")
    monkeypatch.setenv("PBKDF2_ITERATIONS", "1000")  # test hızı
    reset_api_key_cache()


@pytest.fixture
def client(_auth_env, tmp_path, monkeypatch):
    monkeypatch.setattr(auth_route, "USERS_STORE_FILE", tmp_path / "users.json")
    from api.limiter import limiter
    limiter.reset()
    from main import app
    return TestClient(app)


def _reg(client, email="ayse@example.com", pw="Gizli123!", name="Ayşe", consent=True):
    return client.post("/auth/register", json={
        "email": email, "password": pw, "name": name, "privacy_consent": consent,
    })


def test_register_returns_token(client):
    r = _reg(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["sub"] == "user:ayse@example.com"
    assert body["role"] == "user"


def test_register_requires_consent(client):
    assert _reg(client, consent=False).status_code == 400


def test_register_duplicate_409(client):
    assert _reg(client).status_code == 200
    assert _reg(client).status_code == 409  # aynı e-posta


def test_register_weak_password_422(client):
    assert _reg(client, pw="kisa").status_code == 422  # < 8 karakter


def test_register_bad_email_422(client):
    assert _reg(client, email="gecersiz").status_code == 422


def test_login_success(client):
    _reg(client)
    r = client.post("/auth/login", json={"email": "Ayse@Example.com", "password": "Gizli123!"})
    assert r.status_code == 200, r.text
    assert r.json()["sub"] == "user:ayse@example.com"  # normalize


def test_login_wrong_password_401(client):
    _reg(client)
    r = client.post("/auth/login", json={"email": "ayse@example.com", "password": "yanlis"})
    assert r.status_code == 401
    assert "hatalı" in r.json()["detail"]


def test_login_unknown_email_401_generic(client):
    """Bilinmeyen e-posta → 401 generic (enumeration koruması: 'yok' demiyor)."""
    r = client.post("/auth/login", json={"email": "yok@example.com", "password": "x"})
    assert r.status_code == 401
    assert r.json()["detail"] == "E-posta veya şifre hatalı"


def test_me_with_registered_token(client):
    token = _reg(client).json()["access_token"]
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sub"] == "user:ayse@example.com"
    assert body["name"] == "Ayşe"
    assert body["email"] == "ayse@example.com"
    assert body["kind"] == "user"


def test_token_does_not_leak_raw_password(client):
    token = _reg(client, pw="SuperGizli99").json()["access_token"]
    assert "SuperGizli99" not in token
