"""emsal_node + GraphRAG traversal entegrasyon testleri — Sprint-4 W3.4."""

from __future__ import annotations

import pytest

from agents.nodes import emsal as emsal_mod
from retrieval.reranker import RerankResult


def _rr(
    chunk_id: str, score: float, *,
    court: str = "Yargıtay", esas: str = "2019", karar: str = "1234",
    extra_text: str = "",
) -> RerankResult:
    """Test fixture — `_format_case_title` court/esas/karar metadata'sından
    title üretir; bu test graph_rag _CASE_ID_RE ile parse edilir.
    """
    return RerankResult(
        chunk_id=chunk_id,
        score=score,
        text=f"text-{chunk_id} {extra_text}",
        source="yargitay",
        source_url=f"https://yargi/{chunk_id}",
        domain="isHukuku",
        metadata={
            "doc_type": "case",
            "court": court,
            "esas_no": esas,
            "karar_no": karar,
        },
        original_score=score * 0.5,
    )


@pytest.fixture
def _mock_emsal_search(monkeypatch):
    """search_with_rerank'i sahte kararlar dönecek şekilde mock."""
    async def fake_rerank(question, top_k=5, candidates_n=20, domain=None):
        # `_format_case_title` court/esas/karar'dan title üretir:
        # "Yargıtay 2019/1234" → _CASE_ID_RE match → case node seed
        return [
            _rr("y-9HD-2019-1234", 0.92, esas="2019", karar="1234"),
            _rr("y-22HD-2020-567", 0.85, esas="2020", karar="567"),
        ]
    monkeypatch.setattr(emsal_mod, "search_with_rerank", fake_rerank)


@pytest.fixture
def _build_minimal_graph(monkeypatch):
    """LegalGraph singleton'a 3 node ekle + GRAPH_RAG_ENABLED=True."""
    from retrieval import graph_rag

    graph_rag.reset_graph()
    g = graph_rag.LegalGraph()
    if not g.is_available:
        pytest.skip("networkx mevcut değil")

    # 2 law + 2 case + edge (cites) — case1 fake_rerank ile aynı esas/karar
    law1 = g.add_law("IK", 32)
    law2 = g.add_law("TBK", 299)
    case1 = g.add_case("Yargıtay", "2019", "1234")
    case2 = g.add_case("Yargıtay", "2020", "567")
    g.link(case1, law1, "cites")
    g.link(case2, law2, "cites")

    # Singleton'ı doldur
    monkeypatch.setattr(graph_rag, "_graph_singleton", g)
    monkeypatch.setattr(graph_rag, "GRAPH_RAG_ENABLED", True)
    yield g
    graph_rag.reset_graph()


@pytest.mark.asyncio
async def test_emsal_graph_neighbors_populated_when_enabled(
    _mock_emsal_search, _build_minimal_graph,
):
    """GRAPH_RAG_ENABLED=1 + dolu graph → emsal_graph_neighbors state'e yazılır."""
    state = {"question": "Kıdem tazminatı?", "domain": "isHukuku"}
    out = await emsal_mod.emsal_node(state)   # type: ignore[arg-type]

    assert "emsal_refs" in out
    # GraphRAG title regex'i "İK m.32" gibi paternleri yakalar, hops=2 ile
    # bağlı law node'larını döner.
    assert "emsal_graph_neighbors" in out
    assert isinstance(out["emsal_graph_neighbors"], list)
    # En az 1 law neighbor (case → law cites edge)
    law_neighbors = [n for n in out["emsal_graph_neighbors"] if n.startswith("law:")]
    assert len(law_neighbors) >= 1


@pytest.mark.asyncio
async def test_emsal_no_graph_when_disabled(_mock_emsal_search, monkeypatch):
    """GRAPH_RAG_ENABLED=0 → emsal_graph_neighbors yazılmaz (eski davranış)."""
    from retrieval import graph_rag

    graph_rag.reset_graph()
    monkeypatch.setattr(graph_rag, "GRAPH_RAG_ENABLED", False)

    state = {"question": "Kıdem tazminatı?", "domain": "isHukuku"}
    out = await emsal_mod.emsal_node(state)   # type: ignore[arg-type]

    assert "emsal_refs" in out
    assert "emsal_graph_neighbors" not in out


@pytest.mark.asyncio
async def test_emsal_unknown_domain_returns_empty(_mock_emsal_search):
    """domain='unknown' → erken çıkış, hem ref hem neighbor boş."""
    state = {"question": "?", "domain": "unknown"}
    out = await emsal_mod.emsal_node(state)   # type: ignore[arg-type]
    assert out == {"emsal_refs": []}
    assert "emsal_graph_neighbors" not in out
