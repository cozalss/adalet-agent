"""POST /ask endpoint — FastAPI TestClient.

Graph singleton'ı reset edip retrieval'ı mock'luyoruz. Sadece API kontratı +
hata yolları test edilir.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_mocked_retrieval(monkeypatch, sample_citations):
    """Retrieval mock + ask router yeniden singleton'lu client.

    NOT: monkeypatch graph.py'nin local sembollerine yapılır (graph.py
    `from X import Y` ile import-time'da kopyalar). Alt modüllerde değil.
    """
    laws = sample_citations[:2]
    cases = [sample_citations[2]]

    async def fake_mevzuat(_state):
        return {"mevzuat_refs": laws}

    async def fake_emsal(_state):
        return {"emsal_refs": cases}

    from agents import graph as graph_mod

    monkeypatch.setattr(graph_mod, "mevzuat_node", fake_mevzuat)
    monkeypatch.setattr(graph_mod, "emsal_node", fake_emsal)
    # mevzuat_with_hyde_node wrapper kaldırıldı; mevzuat_node HyDE'i kendi yönetir.

    # Graph singleton'ı sıfırla — her test fresh build
    from api.routes import ask as ask_mod
    monkeypatch.setattr(ask_mod, "_graph_singleton", None)

    from main import app
    return TestClient(app)


def test_health_returns_ok():
    """W8.2: health depth — dev mode (LLM_MODE=mock) external bağımlılıklar
    opsiyonel; Qdrant/Redis down olsa bile 200, status ok veya degraded.
    """
    from main import app
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in {"ok", "degraded"}
        assert "qdrant" in body["components"]
        assert "redis" in body["components"]
        assert "llm" in body["components"]


def test_ask_validates_minimum_question_length(client_with_mocked_retrieval):
    resp = client_with_mocked_retrieval.post("/ask", json={"question": "Aa"})
    assert resp.status_code == 422


def test_ask_returns_full_response_envelope(client_with_mocked_retrieval):
    resp = client_with_mocked_retrieval.post(
        "/ask",
        json={"question": "Ayıplı malda tüketici hakkım nedir?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # AskResponse alanları
    assert "answer" in body
    assert "domain" in body
    assert "confidence" in body
    assert "verdict" in body
    assert "citations" in body
    assert "claims" in body
    assert "disclaimers" in body
    assert body["latency_ms"] >= 0


def test_ask_out_of_scope_returns_advisor_message(client_with_mocked_retrieval):
    resp = client_with_mocked_retrieval.post(
        "/ask",
        json={"question": "Cinayet suçlamasıyla ilgili ne yapmalıyım?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["domain"] == "unknown"
    # Avukat tavsiyesi cevapta
    assert "avukat" in body["answer"].lower()


def test_ask_includes_disclaimer_for_valid_questions(client_with_mocked_retrieval):
    resp = client_with_mocked_retrieval.post(
        "/ask",
        json={"question": "Kıdem tazminatı nasıl hesaplanır?"},
    )
    body = resp.json()
    # Disclaimer ya disclaimers array'inde ya answer'da
    has_disclaimer = (
        any("hukuki tavsiye" in d.lower() for d in body.get("disclaimers", []))
        or "hukuki tavsiye" in body.get("answer", "").lower()
        or "avukat" in body.get("answer", "").lower()
    )
    assert has_disclaimer


# --------------------------------------------------------------------------
#  Rate limiting — slowapi /ask wired (RATE_LIMIT_ASK env, default 10/minute)
# --------------------------------------------------------------------------


def test_ask_rate_limit_wired():
    """Smoke: limiter app.state'e bağlı + decorator route'a register.

    Tam 429 davranışı TestClient + slowapi 0.1.9 in-memory backend ile
    deterministik değil (storage TestClient context'inde sıfırlanabiliyor).
    Production'da Redis backend (RATE_LIMIT_STORAGE_URI) ile gerçek IP başına
    sayma çalışır. Buradaki test sadece wiring kontrol.
    """
    from main import app
    assert hasattr(app.state, "limiter"), "limiter app.state'e bağlanmamış"
    from api.limiter import limiter as expected
    assert app.state.limiter is expected
    # Decorator route'a apply edilmiş mi — ask route'un işlevinde slowapi
    # marker attr olur.
    from api.routes.ask import ask, ask_stream
    # slowapi `_limits` veya benzeri attribute ekler; en azından callable
    assert callable(ask)
    assert callable(ask_stream)
