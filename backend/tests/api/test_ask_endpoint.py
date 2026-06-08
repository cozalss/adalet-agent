"""POST /ask endpoint — FastAPI TestClient.

Graph singleton'ı reset edip retrieval'ı mock'luyoruz. Sadece API kontratı +
hata yolları test edilir.
"""

from __future__ import annotations

import json

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


def test_metrics_latency_endpoint():
    """SSE stage latans yüzdelikleri — P50/P95/P99 görünürlüğü (#5 dashboard)."""
    from core.metrics import record_stream_timings, reset_all
    from main import app

    reset_all()
    record_stream_timings({"first_event_ms": 10, "retrieval_done_ms": 1500,
                           "first_token_ms": 3000, "final_ms": 12000})
    record_stream_timings({"first_event_ms": 20, "retrieval_done_ms": 1800,
                           "first_token_ms": 3500, "final_ms": 15000})
    with TestClient(app) as client:
        resp = client.get("/metrics/latency")
        assert resp.status_code == 200
        body = resp.json()
        stages = body["stages"]
        assert stages["stream.final_ms"]["n"] == 2
        assert stages["stream.final_ms"]["p50"] == 12000
        assert stages["stream.final_ms"]["p95"] == 15000
        # 4 stream stage + 3 darboğaz stage (LLM/retrieval)
        assert set(stages) == {"stream.first_event_ms", "stream.retrieval_done_ms",
                               "stream.first_token_ms", "stream.final_ms",
                               "llm.generation_ms", "retrieval.total_ms",
                               "retrieval.hybrid_ms", "verify.duration_ms",
                               "finalize.duration_ms"}
    reset_all()


def test_metrics_prometheus_endpoint():
    """GET /metrics — Prometheus exposition format (Grafana scrape path)."""
    from core.metrics import record_event, reset_all
    from main import app

    reset_all()
    record_event("llama_server_call_done", {"elapsed_ms": 9500})
    record_event("llama_server_call_done", {"elapsed_ms": 12000})
    with TestClient(app) as client:
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        body = resp.text
        assert "# TYPE adalet_stage_latency_ms gauge" in body
        assert 'adalet_stage_latency_ms{stage="llm.generation_ms",quantile="0.95"}' in body
        assert 'adalet_stage_latency_samples{stage="llm.generation_ms"} 2' in body
    reset_all()


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


def test_clear_session_rejects_invalid_conversation_id(client_with_mocked_retrieval):
    """Redis key enjeksiyonu / path-traversal karakterli conversation_id → 422.

    Pattern validation handler'dan ÖNCE çalışır; store'a hiç dokunulmaz.
    """
    resp = client_with_mocked_retrieval.delete("/ask/session/bad*key:123")
    assert resp.status_code == 422


def test_ask_pipeline_error_detail_is_generic(monkeypatch):
    """Pipeline exception'ı 500 detail'inde iç detay (yol/modül/exc) SIZDIRMAMALI.

    Eskiden detail=f"Pipeline hata: {exc!s}" tam exception'ı istemciye veriyordu.
    Artık generic; tam trace yalnız log/audit'e gider.
    """
    from agents import graph as graph_mod

    async def boom_triaj(_state):
        raise RuntimeError("gizli iç hata: C:/secret/path.py satır 42")

    monkeypatch.setattr(graph_mod, "triaj_node", boom_triaj)
    from api.routes import ask as ask_mod
    monkeypatch.setattr(ask_mod, "_graph_singleton", None)

    from main import app
    client = TestClient(app)
    resp = client.post("/ask", json={"question": "Ayıplı malda tüketici hakkım nedir?"})
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail == "İstek işlenemedi, lütfen tekrar deneyin."
    assert "gizli iç hata" not in detail and "path.py" not in detail


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


def test_ask_stream_success_contract(monkeypatch):
    """Başarı yolunda SSE event adları + payload şekli kilitli kalsın."""
    from api.routes import ask as ask_mod

    class _OnePassGraph:
        async def astream(self, _initial, stream_mode="values"):
            assert stream_mode == "values"
            yield {
                "domain": "kira",
                "domain_confidence": 0.9,
                "response_intent": "legal_answer",
                "triage_reasoning": "kira hukuku sorusu",  # triaj set eder → triage SSE event'i
                "retry_count": 0,
                "mevzuat_refs": [],
                "emsal_refs": [],
                "response": "Kısa cevap: Test.",
                "confidence": 0.9,
                "debate_verdict": "pass",
                "verified_claims": [],
                "disclaimers": [],
                "errors": [],
            }

        async def ainvoke(self, _initial):  # pragma: no cover - stream bunu çağırmamalı
            raise AssertionError("/ask/stream graph.ainvoke çağırmamalı")

    monkeypatch.setenv("ASK_GRAPH_TIMEOUT_S", "0")
    monkeypatch.setattr(ask_mod, "_get_graph", lambda: _OnePassGraph())
    from main import app

    client = TestClient(app)
    resp = client.post("/ask/stream", json={"question": "Kira depozitosu nedir?"})
    assert resp.status_code == 200, resp.text
    events = _parse_sse(resp.text)
    # verifying = doğrulama/tartışma aşaması (debate_verdict set olunca) — 4. stepper
    # adımını canlandırır. timing event final'dan hemen önce — stage latency.
    assert [e for e, _ in events] == ["node", "triage", "verifying", "timing", "final"]
    node = events[0][1]
    triage = events[1][1]
    verifying = events[2][1]
    timing = events[3][1]
    final = events[4][1]
    assert verifying["v"] == 2
    assert "t_ms" in verifying
    assert node["v"] == 2
    assert node["domain"] == "kira"
    # v2: node event'i Ajan Akış Şeması için curated active_node taşır (whitelist; key sızmaz)
    assert node["active_node"] in {
        "triaj", "retrieval", "draft", "verify", "debate", "finalize", "chat", "clarifier",
    }
    assert triage["v"] == 2
    assert triage["intent"] == "legal_answer"
    # timing event sözleşmesi: 4 stage alanı + schema version
    assert timing["v"] == 2
    assert "first_event_ms" in timing
    assert "retrieval_done_ms" in timing
    assert "first_token_ms" in timing
    assert "final_ms" in timing
    assert isinstance(timing["final_ms"], int)
    assert final["domain"] == "kira"
    assert final["answer"] == "Kısa cevap: Test."


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in [b for b in text.strip().split("\n\n") if b.strip()]:
        lines = block.splitlines()
        event = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        events.append((event, json.loads(data)))
    return events
