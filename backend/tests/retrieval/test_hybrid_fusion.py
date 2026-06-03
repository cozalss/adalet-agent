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
