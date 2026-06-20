"""POST /emsal/full-text — karar tam metni endpoint (fetch mock'lu, ağ yok)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _client_with_fetch(monkeypatch, result):
    async def fake_fetch(source_url, source_id="", court="", **_k):
        return result

    from api.routes import emsal as emsal_mod
    monkeypatch.setattr(emsal_mod, "fetch_full_decision", fake_fetch)
    from main import app
    return TestClient(app)


def test_full_text_returns_decision(monkeypatch):
    client = _client_with_fetch(
        monkeypatch, {"text": "**8. HD 2011/5172** İçtihat Metni ...", "cached": False, "error": None}
    )
    r = client.post("/emsal/full-text", json={
        "source_url": "https://karararama.yargitay.gov.tr/?aranan=525485900",
        "source_id": "h-525485900-c1",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["text"].startswith("**8. HD")
    assert body["error"] is None
    assert body["cached"] is False


def test_full_text_error_passthrough(monkeypatch):
    client = _client_with_fetch(monkeypatch, {"text": "", "cached": False, "error": "not_found"})
    r = client.post("/emsal/full-text", json={"source_url": "https://karararama.yargitay.gov.tr/?aranan=1"})
    assert r.status_code == 200
    assert r.json() == {"text": "", "cached": False, "error": "not_found"}


def test_full_text_validates_oversize_url(monkeypatch):
    client = _client_with_fetch(monkeypatch, {"text": "x", "cached": False, "error": None})
    r = client.post("/emsal/full-text", json={"source_url": "h" * 700})  # max_length=600
    assert r.status_code == 422  # Pydantic validation


def test_full_text_rejects_non_http_scheme(monkeypatch):
    # ECC: file:// / javascript: gibi şemalar reddedilir (SSRF/şema-injeksiyon).
    client = _client_with_fetch(monkeypatch, {"text": "x", "cached": False, "error": None})
    r = client.post("/emsal/full-text", json={"source_url": "file:///etc/passwd"})
    assert r.status_code == 422
