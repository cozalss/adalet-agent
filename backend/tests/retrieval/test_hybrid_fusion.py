"""retrieval/hybrid_search._fusion_for — RRF/DBSF füzyon seçimi (Context7/Qdrant, ablation knob).

DBSF (Distribution-Based Score Fusion, Qdrant 1.10+) skorları normalize edip toplar →
farklı skor-dağılımlı sparse+dense'i birleştirmede RRF'den robust olabilir. HYBRID_FUSION=dbsf
ile A/B ölçülür. Default rrf → davranış değişmez (geriye-uyumlu).
"""

from __future__ import annotations

import retrieval.hybrid_search as hs


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
