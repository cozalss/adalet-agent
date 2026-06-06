"""retrieval/hybrid_search._fusion_for — RRF/DBSF füzyon seçimi (Context7/Qdrant, ablation knob).

DBSF (Distribution-Based Score Fusion, Qdrant 1.10+) skorları normalize edip toplar →
farklı skor-dağılımlı sparse+dense'i birleştirmede RRF'den robust olabilir. HYBRID_FUSION=dbsf
ile A/B ölçülür. Default rrf → davranış değişmez (geriye-uyumlu).
"""

from __future__ import annotations

import pytest

import retrieval.hybrid_search as hs
from retrieval.embedding import Embedder
from retrieval.hybrid_search import SearchResult


def test_fusion_for_default_is_rrf(monkeypatch):
    monkeypatch.setattr(hs, "_HYBRID_FUSION", "rrf")
    assert hs._fusion_for(2) == hs.models.Fusion.RRF
    assert hs._fusion_for(1) == hs.models.Fusion.RRF


def test_fusion_for_dbsf_requires_two_arms(monkeypatch):
    """DBSF yalnız ≥2 prefetch (sparse+dense) birleşirken anlamlı; tek-kol → RRF."""
    monkeypatch.setattr(hs, "_HYBRID_FUSION", "dbsf")
    assert hs._fusion_for(2) == hs.models.Fusion.DBSF
    assert hs._fusion_for(3) == hs.models.Fusion.DBSF
    assert hs._fusion_for(1) == hs.models.Fusion.RRF  # dense-only Mursit → RRF


def test_fusion_for_unknown_value_falls_back_to_rrf(monkeypatch):
    monkeypatch.setattr(hs, "_HYBRID_FUSION", "garip")
    assert hs._fusion_for(2) == hs.models.Fusion.RRF


# --- maybe_dual_sparse: HyDE + search() paylaşımlı BM25 aktivasyonu (denetim 2026-06-04) ---


class _FakeSparseEmbedder:
    async def aencode_query(self, question):
        return ([0.1], ([1, 5], [0.4, 0.3]), None)  # (dense, (sparse_idx, sparse_val), colbert)


async def test_maybe_dual_sparse_activates_for_sparse_critical_domain(monkeypatch):
    """Mursit sparse boş + domain sparse-kritik (vergi) → BGE-M3 BM25 aktive olur."""
    monkeypatch.setattr(hs, "_SPARSE_MODEL", "BAAI/bge-m3")
    monkeypatch.setattr(hs, "_SPARSE_DOMAINS", frozenset({"vergi", "trafik", "icra"}))
    monkeypatch.setattr(hs, "_get_sparse_embedder", lambda: _FakeSparseEmbedder())
    idx, val = await hs.maybe_dual_sparse("vergi cezası sorusu", [], [], "vergi")
    assert idx == [1, 5] and val == [0.4, 0.3]


async def test_maybe_dual_sparse_skips_non_sparse_domain(monkeypatch):
    """sparse-kritik OLMAYAN domain (tuketici) → sparse boş kalır (regresyon önlenir)."""
    monkeypatch.setattr(hs, "_SPARSE_MODEL", "BAAI/bge-m3")
    monkeypatch.setattr(hs, "_SPARSE_DOMAINS", frozenset({"vergi"}))
    idx, val = await hs.maybe_dual_sparse("iade sorusu", [], [], "tuketici")
    assert idx == [] and val == []


async def test_maybe_dual_sparse_keeps_existing_sparse(monkeypatch):
    """Sparse zaten doluysa (BGE-M3 embedder) embedder çağrılmaz, aynen döner."""
    monkeypatch.setattr(hs, "_SPARSE_MODEL", "BAAI/bge-m3")
    monkeypatch.setattr(hs, "_SPARSE_DOMAINS", frozenset({"vergi"}))
    idx, val = await hs.maybe_dual_sparse("soru", [9], [0.5], "vergi")
    assert idx == [9] and val == [0.5]


async def test_maybe_dual_sparse_no_model_is_noop(monkeypatch):
    """SPARSE_EMBEDDER_MODEL yoksa (tek embedder) → no-op."""
    monkeypatch.setattr(hs, "_SPARSE_MODEL", "")
    idx, val = await hs.maybe_dual_sparse("soru", [], [], "vergi")
    assert idx == [] and val == []


# --- colbert-rerank (RERANK_PROVIDER=bgem3) branch: reorder + empty-guard ---


@pytest.mark.asyncio
async def test_colbert_rerank_reorders_by_score_and_sinks_empty(monkeypatch):
    """RERANK_PROVIDER=bgem3 → BGE-M3 skoruna göre reorder; boş-metin aday en sona (review LOW)."""
    cands = [
        SearchResult(chunk_id=f"c{i}", score=0.5, text=t, source="s", source_url="",
                     domain="kira", metadata={})
        for i, t in enumerate(["Aaa", "Bbb", "Ccc", "   "])  # 4. whitespace
    ]

    async def _fake_search(**kwargs):
        return cands

    fake_emb = Embedder("dummy-no-load")
    # rerank_scores'u override et (model yüklenmez); A=0.1, B=0.9, C=0.5 → boş hariç
    fake_emb.rerank_scores = lambda _q, passages, _w=None: [0.1, 0.9, 0.5][: len(passages)]  # type: ignore[assignment]

    monkeypatch.setenv("RERANK_PROVIDER", "bgem3")
    monkeypatch.setenv("COLBERT_RERANK_MODE", "compute")  # stored-Qdrant yolunu atla → compute (mock)
    monkeypatch.setattr(hs, "search", _fake_search)
    monkeypatch.setattr(hs, "_get_colbert_embedder", lambda: fake_emb)

    out = await hs.search_with_rerank("soru", top_k=4, candidates_n=10)
    # B(0.9) > C(0.5) > A(0.1) > boş(-1.0)
    assert [r.chunk_id for r in out] == ["c1", "c2", "c0", "c3"]
    assert out[-1].chunk_id == "c3"  # whitespace en sonda
