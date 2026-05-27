"""Sprint-7/8 graph topology — Self-RAG / CRAG opsiyonel akışı doğrula.

Default (env=0) Sprint-3 baseline ile birebir aynı: 7 node.
Bayraklar açıkken graph ek node alır; flow sonu yine finalize → END.
"""

from __future__ import annotations

import pytest

from agents.graph import build_graph, make_initial_state
from agents.state import Citation


@pytest.fixture
def mocked_retrieval(monkeypatch, sample_citations):
    laws: list[Citation] = sample_citations[:2]
    cases: list[Citation] = [sample_citations[2]]

    async def fake_mevzuat(_state):
        return {"mevzuat_refs": laws}

    async def fake_emsal(_state):
        return {"emsal_refs": cases}

    from agents import graph as graph_mod
    monkeypatch.setattr(graph_mod, "mevzuat_node", fake_mevzuat)
    monkeypatch.setattr(graph_mod, "emsal_node", fake_emsal)
    # mevzuat_with_hyde_node wrapper kaldırıldı; mevzuat_node HyDE'i kendi yönetir.
    return laws, cases


def test_graph_default_topology_unchanged(monkeypatch):
    """Bayraklar kapalıyken graph node sayısı Sprint-3 baseline kadar (7)."""
    monkeypatch.delenv("CRAG_ENABLED", raising=False)
    monkeypatch.delenv("SELF_RAG_ENABLED", raising=False)
    g = build_graph()
    # LangGraph compiled graph: get_graph().nodes erişimi
    nodes = set(g.get_graph().nodes.keys())
    # __start__/__end__ + 7 ajan
    expected_min = {
        "triaj", "mevzuat", "emsal", "draft", "verify", "debate", "finalize",
    }
    assert expected_min.issubset(nodes)
    assert "crag" not in nodes
    assert "self_rag" not in nodes


def test_graph_with_crag_enabled(monkeypatch):
    """CRAG_ENABLED=1 → 'crag' node graph'a eklenir."""
    monkeypatch.setenv("CRAG_ENABLED", "1")
    monkeypatch.delenv("SELF_RAG_ENABLED", raising=False)
    g = build_graph()
    nodes = set(g.get_graph().nodes.keys())
    assert "crag" in nodes
    assert "self_rag" not in nodes


def test_graph_with_self_rag_enabled(monkeypatch):
    """SELF_RAG_ENABLED=1 → 'self_rag' node graph'a eklenir."""
    monkeypatch.delenv("CRAG_ENABLED", raising=False)
    monkeypatch.setenv("SELF_RAG_ENABLED", "1")
    g = build_graph()
    nodes = set(g.get_graph().nodes.keys())
    assert "self_rag" in nodes
    assert "crag" not in nodes


def test_graph_eligibility_disabled_not_in_topology(monkeypatch):
    """ELIGIBILITY_ENABLED=0 → 'eligibility' node yok, mevzuat→draft korunur."""
    monkeypatch.setenv("ELIGIBILITY_ENABLED", "0")
    monkeypatch.delenv("CRAG_ENABLED", raising=False)
    g = build_graph()
    gg = g.get_graph()
    nodes = set(gg.nodes.keys())
    assert "eligibility" not in nodes
    edges = {(e.source, e.target) for e in gg.edges}
    assert ("mevzuat", "draft") in edges


def test_graph_eligibility_enabled_between_fanin_and_draft(monkeypatch):
    """ELIGIBILITY_ENABLED=1 → fan-in 'eligibility'ye, o da 'draft'a bağlanır."""
    monkeypatch.setenv("ELIGIBILITY_ENABLED", "1")
    monkeypatch.delenv("CRAG_ENABLED", raising=False)
    g = build_graph()
    gg = g.get_graph()
    nodes = set(gg.nodes.keys())
    assert "eligibility" in nodes
    edges = {(e.source, e.target) for e in gg.edges}
    # fan-in → eligibility → draft; doğrudan mevzuat→draft OLMAMALI
    assert ("mevzuat", "eligibility") in edges
    assert ("emsal", "eligibility") in edges
    assert ("eligibility", "draft") in edges
    assert ("mevzuat", "draft") not in edges


def test_graph_both_enabled(monkeypatch):
    """Hem CRAG hem Self-RAG → ikisi de eklenir."""
    monkeypatch.setenv("CRAG_ENABLED", "1")
    monkeypatch.setenv("SELF_RAG_ENABLED", "1")
    g = build_graph()
    nodes = set(g.get_graph().nodes.keys())
    assert "crag" in nodes
    assert "self_rag" in nodes


@pytest.mark.asyncio
async def test_graph_e2e_with_crag_enabled(monkeypatch, mocked_retrieval):
    """CRAG_ENABLED=1 ile graph hala uçtan uca çalışır (akış kırılmaz)."""
    monkeypatch.setenv("CRAG_ENABLED", "1")
    monkeypatch.delenv("SELF_RAG_ENABLED", raising=False)
    g = build_graph()
    state = make_initial_state("Ayıplı malda iade hakkım nedir?")
    result = await g.ainvoke(state)
    assert isinstance(result.get("response"), str)
    assert result.get("debate_verdict") in {"pass", "retry", "reject"}


@pytest.mark.asyncio
async def test_graph_e2e_with_self_rag_enabled(monkeypatch, mocked_retrieval):
    """SELF_RAG_ENABLED=1 ile graph hala uçtan uca çalışır."""
    monkeypatch.delenv("CRAG_ENABLED", raising=False)
    monkeypatch.setenv("SELF_RAG_ENABLED", "1")
    g = build_graph()
    state = make_initial_state("Kıdem tazminatı için kaç yıl şart?")
    result = await g.ainvoke(state)
    assert isinstance(result.get("response"), str)
    assert result.get("debate_verdict") in {"pass", "retry", "reject"}
