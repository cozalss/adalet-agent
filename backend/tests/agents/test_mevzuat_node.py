"""mevzuat_node — pre-domain boost ve fallback davranışları (Sprint-4 W1).

Sprint-4 W1.4 (Pre-domain LLM classify filter):
- Triaj domain'i → DOMAIN_TO_KANUN_KODU mapping → post-retrieve boost
- Domain uyumsuz / mapping yok → boost atlanır, orijinal sıra korunur
- MEVZUAT_DOMAIN_FILTER_ENABLED=0 → boost atlanır
"""

from __future__ import annotations

import pytest

from agents.nodes import mevzuat as mevzuat_mod
from retrieval.hybrid_search import SearchResult


def _sr(
    chunk_id: str, score: float, *, kanun_kodu: str | None = None,
    source: str = "mevzuat",
) -> SearchResult:
    meta = {"doc_type": "law"}
    if kanun_kodu:
        meta["kanun_kodu"] = kanun_kodu
    return SearchResult(
        chunk_id=chunk_id,
        score=score,
        text=f"text-{chunk_id}",
        source=source,
        source_url=f"https://mevzuat/{chunk_id}",
        domain="",
        metadata=meta,
    )


def test_boost_promotes_matching_kanun_kodu():
    """isHukuku → IK. IK'li chunk'lar boost ile öne çıkar.

    Sprint-5 W12 fix: payload'da `kanun_kodu` ALFABETİK (IK, TBK, TKHK).
    Mapping de alfabetik — bu test alfabetik kullanır.
    """
    results = [
        _sr("A", 0.50, kanun_kodu="KTK"),    # KTK (trafik), eşleşmez
        _sr("B", 0.45, kanun_kodu="IK"),     # İş K — eşleşir, boost
        _sr("C", 0.40, kanun_kodu="TPK"),    # Tapu K, eşleşmez
    ]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "isHukuku")
    assert n_boosted == 1
    assert out[0].chunk_id == "B"
    # Boost = 0.15 default → 0.45 + 0.15 = 0.60 > 0.50
    assert out[0].score == pytest.approx(0.60)


def test_boost_preserves_order_when_no_match():
    """Hiçbir kanun_kodu domain'e uymuyorsa orijinal sıra korunur."""
    results = [
        _sr("A", 0.50, kanun_kodu="DMK"),    # DMK (idari/isHukuku), trafik'te eşleşmez
        _sr("B", 0.45, kanun_kodu="TPK"),    # Tapu K, trafik'te eşleşmez
    ]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "trafik")
    assert n_boosted == 0
    assert [r.chunk_id for r in out] == ["A", "B"]


def test_boost_handles_missing_kanun_kodu():
    """`kanun_kodu` field'ı olmayan chunk'lar boost edilmez ama listede kalır."""
    results = [
        _sr("A", 0.50),                       # kanun_kodu yok
        _sr("B", 0.45, kanun_kodu="IK"),     # eşleşir
    ]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "isHukuku")
    assert n_boosted == 1
    assert out[0].chunk_id == "B"
    # A geride ama kayıp değil
    assert out[1].chunk_id == "A"


def test_boost_unknown_domain_returns_input_unchanged():
    """Mapping'de olmayan domain (örn. 'unknown') → no-op."""
    results = [_sr("A", 0.50, kanun_kodu="IK")]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "unknown")
    assert n_boosted == 0
    assert out == results


def test_boost_sprint5_expanded_tuketici():
    """Sprint-5 W12: tuketici 1→8 kanun. TBK, TTK, BK, Sigortacılık, KVKK, RKHK, Ödeme H.

    Çok-katmanlı atıf hedefi: vatandaş "ayıplı banka hizmeti" sorduğunda
    TKHK + BK + RKHK karışık top-K'da çıkar.

    Boost = 0.15. A=0.10 (no boost) en altta kalmalı.
    """
    results = [
        _sr("A", 0.10, kanun_kodu="IK"),     # isHukuku, eşleşmez (no boost → 0.10)
        _sr("B", 0.25, kanun_kodu="TKHK"),   # TKHK, eşleşir (boost → 0.40)
        _sr("C", 0.20, kanun_kodu="BK"),     # BK, eşleşir (boost → 0.35)
        _sr("D", 0.15, kanun_kodu="KVKK"),   # KVKK, eşleşir (boost → 0.30)
        _sr("E", 0.12, kanun_kodu="RKHK"),   # RKHK, eşleşir (boost → 0.27)
    ]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "tuketici")
    # 4 chunk boost almalı (B, C, D, E hepsi tüketici kapsamında)
    assert n_boosted == 4
    # A (no-match) en altta kalmalı
    ids = [r.chunk_id for r in out]
    assert ids.index("A") == 4


def test_boost_sprint5_kira_includes_kmk():
    """Sprint-5 W12: kira 1→5 kanun. TBK + TMK + KMK + Kentsel Dönüşüm + Belediye.

    Apartman ortak kira sorgusunda KMK m.18 hit gelirse boost almalı.
    """
    results = [
        _sr("A", 0.50, kanun_kodu="TKHK"),   # TKHK, eşleşmez
        _sr("B", 0.40, kanun_kodu="KMK"),    # KMK, eşleşir
        _sr("C", 0.30, kanun_kodu="TBK"),    # TBK, eşleşir
    ]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "kira")
    assert n_boosted == 2
    # B + boost = 0.55, A = 0.50 → B önce
    assert out[0].chunk_id == "B"


def test_boost_multi_kodu_domain():
    """Vergi domain'i 10 farklı kanun (Sprint-5 W12 sonrası alfabetik kodlar)."""
    results = [
        _sr("A", 0.40, kanun_kodu="IK"),     # yüksek skor ama yanlış domain
        _sr("B", 0.25, kanun_kodu="VUK"),    # VUK → 0.40 boosted
        _sr("C", 0.20, kanun_kodu="KDV"),    # KDV → 0.35 boosted
        _sr("D", 0.10, kanun_kodu="GVK"),    # GVK → 0.25 boosted
    ]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "vergi")
    assert n_boosted == 3
    ids = [r.chunk_id for r in out]
    assert ids.index("D") == 3
    assert ids.index("A") <= 1
    assert ids.index("B") <= 2
    assert ids.index("C") <= 3
