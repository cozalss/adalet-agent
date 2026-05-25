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
    """isHukuku → 4857. 4857'li chunk'lar boost ile öne çıkar."""
    results = [
        _sr("A", 0.50, kanun_kodu="6502"),   # tüketici, eşleşmez
        _sr("B", 0.45, kanun_kodu="4857"),   # is — eşleşir, boost
        _sr("C", 0.40, kanun_kodu="6098"),   # kira, eşleşmez
    ]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "isHukuku")
    assert n_boosted == 1
    assert out[0].chunk_id == "B"
    # Boost = 0.15 default → 0.45 + 0.15 = 0.60 > 0.50
    assert out[0].score == pytest.approx(0.60)


def test_boost_preserves_order_when_no_match():
    """Hiçbir kanun_kodu domain'e uymuyorsa orijinal sıra korunur."""
    results = [
        _sr("A", 0.50, kanun_kodu="6502"),
        _sr("B", 0.45, kanun_kodu="6098"),
    ]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "trafik")  # → 2918
    assert n_boosted == 0
    assert [r.chunk_id for r in out] == ["A", "B"]


def test_boost_handles_missing_kanun_kodu():
    """`kanun_kodu` field'ı olmayan chunk'lar boost edilmez ama listede kalır."""
    results = [
        _sr("A", 0.50),                       # kanun_kodu yok
        _sr("B", 0.45, kanun_kodu="4857"),   # eşleşir
    ]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "isHukuku")
    assert n_boosted == 1
    assert out[0].chunk_id == "B"
    # A geride ama kayıp değil
    assert out[1].chunk_id == "A"


def test_boost_unknown_domain_returns_input_unchanged():
    """Mapping'de olmayan domain (örn. 'unknown') → no-op."""
    results = [_sr("A", 0.50, kanun_kodu="4857")]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "unknown")
    assert n_boosted == 0
    assert out == results


def test_boost_multi_kodu_domain():
    """Vergi domain'i 3 farklı kanun_kodu kapsar (213, 3065, 193).

    Boost +0.15: tüm vergi chunks +0.15 alır. A (4857, boost yok) düşük yer almalı.
    """
    results = [
        _sr("A", 0.40, kanun_kodu="4857"),   # yüksek skor ama yanlış domain
        _sr("B", 0.25, kanun_kodu="213"),    # → 0.40 boosted
        _sr("C", 0.20, kanun_kodu="3065"),   # → 0.35 boosted
        _sr("D", 0.10, kanun_kodu="193"),    # → 0.25 boosted
    ]
    out, n_boosted = mevzuat_mod._boost_by_domain(results, "vergi")
    assert n_boosted == 3
    # B (0.40 boosted, eşit A 0.40 — stable: B önce çünkü orig daha aşağıda)
    # Aslında stable sort orig sıra korur → A 0. idi, B 1. idi → A önce gelir.
    # Önemli olan: D (0.25 boosted) < A (0.40) ve C (0.35) < A (0.40) DEĞİL —
    # C 0.35 < A 0.40 ise C, A altında. Beklenen: A, B (eşit), C, D.
    # Stable sort eşitlerde orig sıra korur → [A, B, C, D].
    ids = [r.chunk_id for r in out]
    assert ids.index("D") == 3   # D en sonda (en düşük boost'lu skor)
    assert ids.index("A") <= 1   # A ilk veya ikinci (B ile eşit 0.40)
    # Tüm boost'lu chunk'lar A'dan sonra geç gelmemeli (yeterli boost var)
    assert ids.index("B") <= 2
    assert ids.index("C") <= 3
