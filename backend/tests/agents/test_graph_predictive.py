"""PREDICTIVE_ENABLED — 8. ajan (tahmin) graph entegrasyonu (W18).

Flag açıkken finalize öncesi `tahmin` node araya girer ve final state'e
`prediction` ekler; kapalıyken topoloji baseline ile aynı (prediction None).
"""

from __future__ import annotations

import pytest

from agents.state import Citation


def _case(sid: str, snippet: str) -> Citation:
    return Citation(
        source_id=sid, doc_type="case", title=f"Yargıtay {sid}",
        snippet=snippet, url=f"https://yargi.gov.tr/{sid}", score=0.8,
    )


def _law(sid: str) -> Citation:
    return Citation(
        source_id=sid, doc_type="law", title=f"Kanun {sid}",
        snippet="İlgili kanun maddesi metni.", url=f"https://mevzuat.gov.tr/{sid}",
        score=0.8,
    )


@pytest.fixture
def _force_happy_path(monkeypatch):
    """triaj/verify/debate'i deterministik pass'e zorla — tahmin wiring'ine odak."""
    from agents import graph as graph_mod

    async def fake_triaj(_s):
        return {"domain": "isHukuku", "domain_confidence": 0.9, "triage_reasoning": "test"}

    async def fake_mevzuat(_s):
        return {"mevzuat_refs": [_law("m1")]}

    async def fake_emsal(_s):
        return {"emsal_refs": [
            _case("c1", "davanın kabulüne karar verildi"),
            _case("c2", "talebin kabulüne karar verildi"),
            _case("c3", "davanın reddine karar verildi"),
        ]}

    async def fake_verify(_s):
        return {"verified_claims": [], "debate_verdict": "pass"}

    async def fake_debate(_s):
        return {"debate_verdict": "pass", "debate_notes": "ok"}

    monkeypatch.setattr(graph_mod, "triaj_node", fake_triaj)
    monkeypatch.setattr(graph_mod, "mevzuat_node", fake_mevzuat)
    monkeypatch.setattr(graph_mod, "emsal_node", fake_emsal)
    monkeypatch.setattr(graph_mod, "verify_node", fake_verify)
    monkeypatch.setattr(graph_mod, "debate_node", fake_debate)


@pytest.mark.asyncio
async def test_graph_produces_prediction_when_enabled(monkeypatch, _force_happy_path):
    monkeypatch.setenv("PREDICTIVE_ENABLED", "1")
    from agents.graph import build_graph, make_initial_state

    graph = build_graph()
    result = await graph.ainvoke(make_initial_state("Kıdem tazminatı alabilir miyim?"))

    pred = result.get("prediction")
    assert pred is not None, "PREDICTIVE_ENABLED=1 iken prediction üretilmeli"
    # 2 kabul + 1 ret → çoğunluk kazandi
    assert pred["verdict_class"] == "kazandi"
    assert 0.0 < pred["confidence"] <= 0.85
    assert pred["similar_case_ids"] == ["c1", "c2", "c3"]


@pytest.mark.asyncio
async def test_graph_no_prediction_when_disabled(monkeypatch, _force_happy_path):
    monkeypatch.setenv("PREDICTIVE_ENABLED", "0")
    from agents.graph import build_graph, make_initial_state

    graph = build_graph()
    result = await graph.ainvoke(make_initial_state("Kıdem tazminatı alabilir miyim?"))
    # Flag kapalı → tahmin node yok → prediction set edilmez (baseline).
    assert result.get("prediction") is None


@pytest.mark.asyncio
async def test_predictive_disabled_topology_unchanged(monkeypatch):
    """Flag kapalıyken compiled graph 'tahmin' node içermemeli (baseline koruması)."""
    monkeypatch.setenv("PREDICTIVE_ENABLED", "0")
    from agents.graph import build_graph

    graph = build_graph()
    node_ids = set(graph.get_graph().nodes)
    assert "tahmin" not in node_ids


@pytest.mark.asyncio
async def test_predictive_enabled_adds_node(monkeypatch):
    monkeypatch.setenv("PREDICTIVE_ENABLED", "1")
    from agents.graph import build_graph

    graph = build_graph()
    node_ids = set(graph.get_graph().nodes)
    assert "tahmin" in node_ids
