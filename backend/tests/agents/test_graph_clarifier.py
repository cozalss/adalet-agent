"""Clarifier graph entegrasyonu — routing + dur-ve-sor akışı.

`_route_after_triaj` artık policy engine'i tüketiyor. clarify dalı retrieval'a
HİÇ girmeden finalize'da bitmeli (takip soruları döner).
"""

from __future__ import annotations

import pytest

from agents.graph import _route_after_triaj, build_graph, make_initial_state
from agents.policy import CLARIFY_MARKER

# --- routing (saf, graph build yok) ---

def test_route_clarify_for_sparse_valid_domain():
    state = {
        "domain": "kira",
        "response_intent": "legal_answer",
        "case_facts": {},
    }
    assert _route_after_triaj(state) == "clarifier"


def test_route_answer_when_facts_sufficient():
    state = {
        "domain": "kira",
        "response_intent": "legal_answer",
        "case_facts": {"olay": "depozito iade edilmiyor", "tutar": "5000 TL"},
    }
    assert _route_after_triaj(state) == ["mevzuat", "emsal"]


def test_route_unknown_goes_to_sink_not_clarifier():
    state = {"domain": "unknown", "response_intent": "redirect_to_scope"}
    out = _route_after_triaj(state)
    assert out != "clarifier"
    assert out != ["mevzuat", "emsal"]


# --- full graph: clarify path skips retrieval ---

@pytest.fixture
def spied_retrieval(monkeypatch):
    """mevzuat/emsal'i çağrı sayan spy'lara bağla — clarify dalında 0 olmalı."""
    calls = {"mevzuat": 0, "emsal": 0}

    async def spy_mevzuat(_state):
        calls["mevzuat"] += 1
        return {"mevzuat_refs": []}

    async def spy_emsal(_state):
        calls["emsal"] += 1
        return {"emsal_refs": []}

    from agents import graph as graph_mod

    monkeypatch.setattr(graph_mod, "mevzuat_node", spy_mevzuat)
    monkeypatch.setattr(graph_mod, "emsal_node", spy_emsal)
    return calls


@pytest.mark.asyncio
async def test_clarify_path_never_calls_retrieval(spied_retrieval, monkeypatch):
    """Eksik-bilgili kira sorusu → clarifier → finalize, retrieval atlanır."""
    async def fake_triaj(_state):
        return {
            "domain": "kira",
            "domain_confidence": 0.9,
            "triage_reasoning": "test",
            "response_intent": "legal_answer",
            "case_facts": {},
        }

    from agents import graph as graph_mod
    monkeypatch.setattr(graph_mod, "triaj_node", fake_triaj)

    graph = build_graph()
    state = make_initial_state("kira depozitomu alamıyorum")
    result = await graph.ainvoke(state)

    # Retrieval'a hiç girilmedi.
    assert spied_retrieval["mevzuat"] == 0
    assert spied_retrieval["emsal"] == 0
    # Takip soruları kullanıcıya döndü.
    assert CLARIFY_MARKER in result["response"]
    assert result["response_intent"] == "needs_clarification"
    assert result["confidence"] == 0.0
    # Hukuki disclaimer/kaynak bloğu yok (sadece soru).
    assert "Kaynaklar" not in result["response"]


@pytest.mark.asyncio
async def test_sufficient_facts_path_calls_retrieval(spied_retrieval, monkeypatch):
    """Yeterli olgu → answer dalı → retrieval çağrılır (baseline korunur)."""
    async def fake_triaj(_state):
        return {
            "domain": "kira",
            "domain_confidence": 0.9,
            "triage_reasoning": "test",
            "response_intent": "legal_answer",
            "case_facts": {"olay": "depozito iade edilmiyor", "tarih": "2026-01"},
        }

    from agents import graph as graph_mod
    monkeypatch.setattr(graph_mod, "triaj_node", fake_triaj)

    graph = build_graph()
    state = make_initial_state("kira depozitom 5000 TL, sözleşme bitti, teslim ettim")
    result = await graph.ainvoke(state)

    assert spied_retrieval["mevzuat"] == 1
    assert spied_retrieval["emsal"] == 1
    assert result.get("response_intent") != "needs_clarification"
