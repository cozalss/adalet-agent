"""GraphRAG — NetworkX-based legal knowledge graph tests.

NetworkX yoksa modül no-op; testler graceful skip.
"""

from __future__ import annotations

import os

import pytest

# Graph'ı etkinleştir
os.environ["GRAPH_RAG_ENABLED"] = "1"

nx = pytest.importorskip("networkx")

from retrieval.graph_rag import (  # noqa: E402
    GRAPH_RAG_ENABLED,
    LegalGraph,
    _slug,
    extract_seed_ids,
)


def test_legal_graph_construction():
    """Law + Case + Concept eklenir, link'ler kurulur."""
    g = LegalGraph()
    assert g.is_available is True

    law1 = g.add_law("TKHK", 11)
    law2 = g.add_law("IK", 32)
    case1 = g.add_case("Yargıtay", "2019", "1234")
    concept = g.add_concept("kıdem tazminatı")

    g.link(case1, law2, "cites")
    g.link(law2, concept, "governs")
    g.link(law1, g.add_concept("ayıplı mal"), "governs")

    assert g.n_nodes == 5
    assert g.n_edges == 3


def test_legal_graph_expand_bfs():
    """Seed'ten 2-hop expand → komşu node'ları döndür."""
    g = LegalGraph()
    law = g.add_law("TKHK", 11)
    concept = g.add_concept("ayıplı mal")
    case = g.add_case("Yargıtay", "2018", "5678")
    g.link(case, law, "cites")
    g.link(law, concept, "governs")

    hits = g.expand([law], hops=2, max_nodes=10)
    ids = {h.node.node_id for h in hits}
    assert law in ids
    # case ve concept de hop=1 mesafede ulaşılabilir (incoming/outgoing edge)
    assert case in ids or concept in ids
    # distance scoring monotone
    for h in hits:
        assert h.score == pytest.approx(1.0 / (h.distance + 1), abs=1e-6)


def test_legal_graph_expand_empty_seeds():
    """Boş seed → boş hit listesi."""
    g = LegalGraph()
    g.add_law("TKHK", 11)
    assert g.expand([]) == []
    assert g.expand(["law:NONEXISTENT:999"]) == []


def test_extract_seed_ids_law():
    titles = [
        "TKHK Madde 11",
        "İK m.32",
        "TBK madde 299",
        "BK 83",
        "alakasız metin",
    ]
    seeds = extract_seed_ids(titles)
    assert "law:TKHK:11" in seeds
    # IK → İK normalize edilmiş hâli upper'da İK kalır
    assert any(s.startswith("law:") and ":32" in s for s in seeds)
    assert "law:TBK:299" in seeds
    assert "law:BK:83" in seeds


def test_extract_seed_ids_case():
    titles = ["Yargıtay 9.HD 2019/1234", "Danıştay 5.D 2020/567"]
    seeds = extract_seed_ids(titles)
    assert any("case:" in s and "2019/1234" in s for s in seeds)
    assert any("case:" in s and "2020/567" in s for s in seeds)


def test_extract_seed_ids_dedupe():
    """Aynı id iki kez geçerse tek seferlik kalır."""
    titles = ["TKHK Madde 11", "TKHK madde 11"]
    seeds = extract_seed_ids(titles)
    assert len([s for s in seeds if s == "law:TKHK:11"]) == 1


def test_slug_turkish_diacritics():
    assert _slug("kıdem tazminatı") == "kidem-tazminati"
    assert _slug("İŞ HUKUKU") == "is-hukuku"
    assert _slug("Ayıplı Mal") == "ayipli-mal"
    assert _slug("") == "concept"
    assert _slug("!!!") == "concept"


def test_graph_save_and_load(tmp_path):
    """Disk persistence round-trip — node + edge sayısı korunmalı."""
    g = LegalGraph()
    g.add_law("TKHK", 11)
    g.add_law("IK", 32)
    g.add_case("Yargıtay", "2019", "1234")
    g.link("case:Yargıtay:2019/1234", "law:IK:32", "cites")

    path = tmp_path / "graph.json"
    g.save(path)
    assert path.exists()

    g2 = LegalGraph.load(path)
    assert g2.n_nodes == g.n_nodes
    assert g2.n_edges == g.n_edges


def test_graph_rag_enabled_flag_set():
    """Test ortamında env=1 olduğu için True olmalı."""
    assert GRAPH_RAG_ENABLED is True
