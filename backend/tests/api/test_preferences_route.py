"""/me/preferences endpoint — auth gate, round-trip, validation, KVKK testleri.

DB kapalı (DATABASE_URL yok) → FilesystemPreferenceRepo; PREFS_STORE_PATH tmp'ye
yönlendirilir. AUTH_ENABLED açık; token ile authed kullanıcı simüle edilir.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.middleware import auth as auth_mod
from api.middleware.auth import issue_token, reset_api_key_cache
from api.routes import preferences as prefs_route


@pytest.fixture
def _auth_env(monkeypatch):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "AUTH_PROVIDER", "internal")  # internal HS256 yolu (Supabase JWKS değil)
    monkeypatch.setattr(auth_mod, "SUPABASE_URL", "")
    monkeypatch.setattr(auth_mod, "JWT_SECRET", "test-secret-32bytes-min-OK-123456")
    monkeypatch.setattr(auth_mod, "JWT_TTL_SECONDS", 3600)
    monkeypatch.setattr(auth_mod, "JWT_ISSUER", "test-iss")
    monkeypatch.setattr(auth_mod, "JWT_AUDIENCE", "test-aud")
    reset_api_key_cache()


@pytest.fixture
def client(_auth_env, tmp_path, monkeypatch):
    # Tercih store'u tmp dosyaya (DB kapalı → filesystem repo).
    monkeypatch.setattr(prefs_route, "PREFS_STORE_PATH", tmp_path / "prefs.json")
    from api.limiter import limiter
    limiter.reset()
    from main import app
    return TestClient(app)


def _auth(sub: str = "beta:alice@example.com") -> dict:
    return {"Authorization": f"Bearer {issue_token(sub, role='beta')}"}


def test_get_anonymous_returns_401(client):
    """Anonim (token yok) → 401; tercih sunucuda saklanmaz, cihazda kalır."""
    assert client.get("/me/preferences").status_code == 401


def test_put_anonymous_returns_401(client):
    r = client.put("/me/preferences", json={"text_scale": "large"})
    assert r.status_code == 401


def test_get_defaults_for_new_user(client):
    """Kaydı olmayan authed kullanıcı → varsayılan tercihler."""
    r = client.get("/me/preferences", headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text_scale"] == "normal"
    assert body["reduce_motion"] is False
    assert body["preferred_domains"] == []


def test_put_then_get_roundtrip(client):
    """PUT kaydeder, GET aynı tercihleri döner (cihazlar-arası kalıcılık)."""
    payload = {
        "display_name": "Ayşe Yılmaz",
        "text_scale": "large",
        "reduce_motion": True,
        "high_contrast": True,
        "preferred_domains": ["kira", "isHukuku"],
    }
    rp = client.put("/me/preferences", json=payload, headers=_auth())
    assert rp.status_code == 200, rp.text

    rg = client.get("/me/preferences", headers=_auth())
    assert rg.status_code == 200
    body = rg.json()
    assert body["display_name"] == "Ayşe Yılmaz"
    assert body["text_scale"] == "large"
    assert body["reduce_motion"] is True
    assert body["preferred_domains"] == ["kira", "isHukuku"]


def test_invalid_text_scale_normalized(client):
    """Bilinmeyen yazı boyutu → 'normal' (savunmacı doğrulama)."""
    r = client.put("/me/preferences", json={"text_scale": "huge"}, headers=_auth())
    assert r.status_code == 200
    assert r.json()["text_scale"] == "normal"


def test_unknown_domains_filtered(client):
    """Kapsam dışı/uydurma alanlar atılır; yalnız 8 sivil alan kalır (ceza yok)."""
    r = client.put(
        "/me/preferences",
        json={"preferred_domains": ["kira", "ceza", "aile", "tuketici", "uydurma"]},
        headers=_auth(),
    )
    assert r.status_code == 200
    assert r.json()["preferred_domains"] == ["kira", "tuketici"]


def test_two_users_isolated(client):
    """Farklı kullanıcılar farklı tercih görür (sub_hash anahtarlı)."""
    client.put("/me/preferences", json={"text_scale": "large"},
               headers=_auth("beta:alice@example.com"))
    client.put("/me/preferences", json={"text_scale": "compact"},
               headers=_auth("beta:bob@example.com"))
    a = client.get("/me/preferences", headers=_auth("beta:alice@example.com")).json()
    b = client.get("/me/preferences", headers=_auth("beta:bob@example.com")).json()
    assert a["text_scale"] == "large"
    assert b["text_scale"] == "compact"


def test_delete_clears_preferences(client):
    """DELETE (KVKK silme hakkı) → sonraki GET varsayılana döner."""
    client.put("/me/preferences", json={"text_scale": "large"}, headers=_auth())
    rd = client.delete("/me/preferences", headers=_auth())
    assert rd.status_code == 204
    assert client.get("/me/preferences", headers=_auth()).json()["text_scale"] == "normal"


def test_store_does_not_contain_raw_email(client, tmp_path, monkeypatch):
    """KVKK: tercih dosyası ham email içermemeli — anahtar fingerprint(sub)."""
    store = tmp_path / "prefs_kvkk.json"
    monkeypatch.setattr(prefs_route, "PREFS_STORE_PATH", store)
    client.put("/me/preferences", json={"text_scale": "large"},
               headers=_auth("beta:alice@example.com"))
    raw = store.read_text(encoding="utf-8")
    assert "alice" not in raw and "@" not in raw and "beta:" not in raw
