"""LangGraph E2E akış testi — retrieval node'ları mock'lu, full graph traversal.

Bu test Qdrant'a gitmez. mevzuat_node ve emsal_node'u monkeypatch ile
deterministic fixture'a bağlar. Amaç: verify+debate+retry wiring'inin
doğru çalıştığını saf graph testinde göstermek.
"""

from __future__ import annotations

import pytest

from agents.graph import build_graph, make_initial_state
from agents.state import Citation


@pytest.fixture
def mocked_retrieval(monkeypatch, sample_citations):
    """mevzuat_node + emsal_node + hyde wrapper'ı state delta dönen lambda ile değiştir.

    Önemli: `agents.graph` modülü `from X import Y` ile sembolleri local'e
    kopyalar. Bu yüzden monkeypatch graph modülünün KENDİ namespace'inde
    yapılmalı, alt modüllerde değil.
    """
    laws: list[Citation] = sample_citations[:2]
    cases: list[Citation] = [sample_citations[2]]

    async def fake_mevzuat(_state):
        return {"mevzuat_refs": laws}

    async def fake_emsal(_state):
        return {"emsal_refs": cases}

    from agents import graph as graph_mod

    monkeypatch.setattr(graph_mod, "mevzuat_node", fake_mevzuat)
    monkeypatch.setattr(graph_mod, "emsal_node", fake_emsal)
    # mevzuat_with_hyde_node wrapper artık graph'tan kaldırıldı (mevzuat_node
    # HyDE/multi-query'i içeride yapıyor). Eski monkeypatch satırı silindi.

    return laws, cases


@pytest.mark.asyncio
async def test_graph_compiles():
    """Graph derleniyor mu?"""
    graph = build_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_graph_e2e_consumer_question(mocked_retrieval):
    """Tüketici hukuku sorusu → verdict pass/retry/reject döner, response var."""
    graph = build_graph()
    state = make_initial_state("Ayıplı malda tüketici hakkım nedir?")
    result = await graph.ainvoke(state)

    # Triaj keyword routing: 'tuketici' veya 'ayıplı' → tuketici domain
    assert result.get("domain") in {"tuketici", "unknown"}
    # Response her zaman üretilir (pass veya reject template)
    assert isinstance(result.get("response"), str)
    assert len(result["response"]) > 0
    # Disclaimer her zaman eklenir
    assert any("hukuki tavsiye" in d.lower() for d in result.get("disclaimers", []))
    # Verdict atanmış
    assert result.get("debate_verdict") in {"pass", "retry", "reject"}


@pytest.mark.asyncio
async def test_graph_out_of_scope_rejects_fast():
    """'Cinayet' → kapsam dışı → triaj unknown → finalize reject."""
    graph = build_graph()
    state = make_initial_state("Cinayetten yargılanıyorum, ne yapayım?")
    result = await graph.ainvoke(state)
    assert result["domain"] == "unknown"
    assert result["confidence"] == 0.0
    # Avukata danışın mesajı
    assert "avukat" in result["response"].lower()


@pytest.mark.asyncio
async def test_graph_retry_limit_terminates(mocked_retrieval, monkeypatch):
    """Verify+debate hep retry derse, MAX_RETRY sonrası reject finalize'a düşer.

    Hem verify hem debate node'unu monkeypatch'liyoruz çünkü MockLLM debate'te
    her zaman "pass" döner — gerçek retry loop'u test edemezdik.
    """
    from agents.config import MAX_RETRY

    async def fake_verify(_state):
        return {
            "verified_claims": [],
            "debate_verdict": "retry",
            "debate_notes": "Test: hep retry",
        }

    async def fake_debate(state):
        retry_count = state.get("retry_count", 0)
        if retry_count >= MAX_RETRY:
            return {
                "debate_verdict": "reject",
                "debate_notes": f"Retry limiti ({MAX_RETRY}) doldu",
            }
        return {
            "debate_verdict": "retry",
            "retry_count": retry_count + 1,
            "debate_notes": f"Test retry #{retry_count + 1}",
        }

    from agents import graph as graph_mod
    monkeypatch.setattr(graph_mod, "verify_node", fake_verify)
    monkeypatch.setattr(graph_mod, "debate_node", fake_debate)

    graph = build_graph()
    state = make_initial_state("Kıdem tazminatı nasıl hesaplanır?")
    result = await graph.ainvoke(state)

    # MAX_RETRY sonrası reject + retry_count guard
    assert result["debate_verdict"] == "reject"
    assert result.get("retry_count", 0) == MAX_RETRY
    assert "limit" in result["debate_notes"].lower()
