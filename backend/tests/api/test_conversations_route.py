"""/me/conversations + /me/files endpoint testleri — auth gate, roundtrip, IDOR."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.middleware import auth as auth_mod
from api.middleware.auth import issue_token, reset_api_key_cache
from api.routes import conversations as conv_route


@pytest.fixture
def _auth_env(monkeypatch):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "JWT_SECRET", "test-secret-32bytes-min-OK-123456")
    monkeypatch.setattr(auth_mod, "JWT_TTL_SECONDS", 3600)
    monkeypatch.setattr(auth_mod, "JWT_ISSUER", "test-iss")
    monkeypatch.setattr(auth_mod, "JWT_AUDIENCE", "test-aud")
    reset_api_key_cache()


@pytest.fixture
def client(_auth_env, tmp_path, monkeypatch):
    monkeypatch.setattr(conv_route, "CONV_STORE_PATH", tmp_path / "conv.json")
    from api.limiter import limiter
    limiter.reset()
    from main import app
    return TestClient(app)


def _auth(sub: str = "beta:alice@example.com") -> dict:
    return {"Authorization": f"Bearer {issue_token(sub, role='beta')}"}


def _conv_body(title: str = "Kira sorunu") -> dict:
    return {
        "title": title, "domain": "kira",
        "messages": [
            {"turn_index": 0, "role": "user", "content": "Ev sahibim zam istiyor"},
            {"turn_index": 1, "role": "assistant", "content": "Yasal sınır TÜFE'dir", "confidence": 88.0},
        ],
    }


def test_list_anonymous_401(client):
    assert client.get("/me/conversations").status_code == 401


def test_upsert_anonymous_401(client):
    assert client.put("/me/conversations/abc123", json=_conv_body()).status_code == 401


def test_upsert_list_get_roundtrip(client):
    rp = client.put("/me/conversations/conv-1", json=_conv_body(), headers=_auth())
    assert rp.status_code == 200, rp.text
    assert rp.json()["message_count"] == 2

    rl = client.get("/me/conversations", headers=_auth())
    assert rl.status_code == 200
    lst = rl.json()
    assert len(lst) == 1 and lst[0]["title"] == "Kira sorunu"

    rg = client.get("/me/conversations/conv-1", headers=_auth())
    assert rg.status_code == 200
    assert len(rg.json()["messages"]) == 2


def test_invalid_id_422(client):
    assert client.get("/me/conversations/bad id!", headers=_auth()).status_code == 422


def test_owner_isolation_idor(client):
    """Bir kullanıcı başkasının sohbetini göremez/silemez."""
    client.put("/me/conversations/c-alice", json=_conv_body(), headers=_auth("beta:alice@example.com"))
    # Bob alice'in sohbetini getiremez (404 — sızıntı yok)
    assert client.get("/me/conversations/c-alice", headers=_auth("beta:bob@example.com")).status_code == 404
    # Bob'un listesi boş
    assert client.get("/me/conversations", headers=_auth("beta:bob@example.com")).json() == []
    # Bob silemez (204 ama no-op; alice'inki durur)
    client.delete("/me/conversations/c-alice", headers=_auth("beta:bob@example.com"))
    assert client.get("/me/conversations/c-alice", headers=_auth("beta:alice@example.com")).status_code == 200


def test_search(client):
    client.put("/me/conversations/c1", json=_conv_body("Kira artışı"), headers=_auth())
    client.put("/me/conversations/c2", json=_conv_body("İşten çıkarılma"), headers=_auth())
    res = client.get("/me/conversations?q=kira", headers=_auth()).json()
    assert len(res) == 1 and res[0]["id"] == "c1"


def test_delete(client):
    client.put("/me/conversations/c1", json=_conv_body(), headers=_auth())
    assert client.delete("/me/conversations/c1", headers=_auth()).status_code == 204
    assert client.get("/me/conversations", headers=_auth()).json() == []


def test_upsert_same_id_isolated_per_owner(client):
    """Filesystem: her kullanıcı kendi bucket'ında — aynı conv_id çakışmaz, ezilmez.

    (Postgres modunda tek tablo PK çakışması → repo upsert False → route 403;
    o yol test_postgres_roundtrip'te repo seviyesinde kapsanır.)
    """
    client.put("/me/conversations/shared-id", json=_conv_body(), headers=_auth("beta:alice@example.com"))
    client.put("/me/conversations/shared-id", json=_conv_body("Bob'un kaydı"),
               headers=_auth("beta:bob@example.com"))
    # İkisi de kendi kaydını görür; Alice'inki bozulmadı (bucket izolasyonu)
    assert client.get("/me/conversations/shared-id", headers=_auth("beta:alice@example.com")).json()["title"] == "Kira sorunu"
    assert client.get("/me/conversations/shared-id", headers=_auth("beta:bob@example.com")).json()["title"] == "Bob'un kaydı"


def test_delete_all(client):
    """Tüm geçmişi tek istekle sil (KVKK)."""
    client.put("/me/conversations/c1", json=_conv_body("A"), headers=_auth())
    client.put("/me/conversations/c2", json=_conv_body("B"), headers=_auth())
    assert len(client.get("/me/conversations", headers=_auth()).json()) == 2
    assert client.delete("/me/conversations", headers=_auth()).status_code == 204
    assert client.get("/me/conversations", headers=_auth()).json() == []


def test_filename_path_traversal_stripped(client):
    """Dosya adındaki yol bileşenleri atılır (traversal önlemi)."""
    client.post("/me/files", json={"filename": "../../etc/passwd", "n_chars": 5}, headers=_auth())
    files = client.get("/me/files", headers=_auth()).json()
    assert files[0]["filename"] == "passwd"


def test_files_roundtrip(client):
    rp = client.post("/me/files", json={"filename": "kira.pdf", "n_chars": 1200, "pii_flag": True},
                     headers=_auth())
    assert rp.status_code == 201
    files = client.get("/me/files", headers=_auth()).json()
    assert len(files) == 1 and files[0]["filename"] == "kira.pdf"
    # owner-scoped
    assert client.get("/me/files", headers=_auth("beta:bob@example.com")).json() == []


def test_store_no_raw_email(client, tmp_path, monkeypatch):
    """KVKK: conversations store ham email içermez (anahtar fingerprint(sub))."""
    store = tmp_path / "conv_kvkk.json"
    monkeypatch.setattr(conv_route, "CONV_STORE_PATH", store)
    client.put("/me/conversations/c1", json=_conv_body(), headers=_auth("beta:alice@example.com"))
    raw = store.read_text(encoding="utf-8")
    assert "alice" not in raw and "beta:" not in raw
