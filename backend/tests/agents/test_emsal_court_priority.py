"""emsal_node mahkeme-öncelikli tier-sort (Step-5).

Anayasa bireysel başvuru corpus'ta hacimce baskın → cross-encoder onları öne
koyuyor. Vatandaş-yardım domain'lerinde esaslı emsal Yargıtay/Danıştay'dır.
Tier-sort tercih edilen mahkemeyi anayasanın üstüne çıkarır (stable → tier
içinde cross-encoder sırası korunur).
"""

from __future__ import annotations

import pytest

from agents.nodes import emsal as emsal_mod
from retrieval.reranker import RerankResult


def _rr(chunk_id: str, score: float, source: str) -> RerankResult:
    return RerankResult(
        chunk_id=chunk_id,
        score=score,
        text=f"karar metni {chunk_id}",
        source=source,
        source_url=f"https://x/{chunk_id}",
        domain="isHukuku",
        metadata={"doc_type": "case", "court": source},
        original_score=score * 0.5,
    )


# --- _court_priority_sort birim ---

def test_yargitay_promoted_over_anayasa_for_ishukuku():
    """Cross-encoder anayasayı #1 koysa bile Yargıtay tier-0'a çıkar."""
    cases = [
        _rr("anaya1", 0.95, "anayasa"),   # cross-encoder #1 ama bireysel başvuru
        _rr("yarg1", 0.40, "yargitay"),   # esaslı emsal, cross-encoder geride
        _rr("anaya2", 0.30, "anayasa"),
        _rr("yarg2", 0.20, "yargitay"),
    ]
    out, n_pref = emsal_mod._court_priority_sort(cases, "isHukuku")
    ids = [c.chunk_id for c in out]
    assert ids[:2] == ["yarg1", "yarg2"]    # tier-0, cross-encoder sırasında
    assert ids[2:] == ["anaya1", "anaya2"]  # tier-2 (anayasa en sona)
    assert n_pref == 2


def test_preserves_cross_encoder_order_within_tier():
    cases = [
        _rr("y1", 0.9, "yargitay"),
        _rr("y2", 0.8, "yargitay"),
        _rr("y3", 0.7, "yargitay"),
    ]
    out, n_pref = emsal_mod._court_priority_sort(cases, "isHukuku")
    assert [c.chunk_id for c in out] == ["y1", "y2", "y3"]
    assert n_pref == 3


def test_danistay_preferred_for_vergi():
    """Vergi domain'inde Danıştay tier-0; Yargıtay tier-1; anayasa tier-2."""
    cases = [
        _rr("ana", 0.99, "anayasa"),
        _rr("yarg", 0.80, "yargitay"),
        _rr("dan", 0.50, "danistay"),
    ]
    out, _ = emsal_mod._court_priority_sort(cases, "vergi")
    assert [c.chunk_id for c in out] == ["dan", "yarg", "ana"]


def test_tapu_prefers_both_yargitay_and_danistay():
    cases = [
        _rr("ana", 0.99, "anayasa"),
        _rr("dan", 0.60, "danistay"),
        _rr("yarg", 0.55, "yargitay"),
    ]
    out, n_pref = emsal_mod._court_priority_sort(cases, "tapu")
    # yargitay+danistay tier-0 (cross-encoder sırasında: dan 0.60 > yarg 0.55)
    assert [c.chunk_id for c in out][:2] == ["dan", "yarg"]
    assert out[2].chunk_id == "ana"
    assert n_pref == 2


def test_domain_without_preference_is_noop():
    """DOMAIN_PREFERRED_COURTS'ta olmayan domain → sıra değişmez."""
    cases = [_rr("a", 0.9, "anayasa"), _rr("b", 0.4, "yargitay")]
    out, n_pref = emsal_mod._court_priority_sort(cases, "bilinmeyen")
    assert [c.chunk_id for c in out] == ["a", "b"]
    assert n_pref == 0


# --- node entegrasyonu: anayasa gürültüsü Yargıtay'ın altına iner ---

@pytest.mark.asyncio
async def test_emsal_node_surfaces_yargitay_over_anayasa(monkeypatch):
    async def fake_rerank(question, top_k=5, candidates_n=20, domain=None):
        return [
            _rr("ana1", 0.95, "anayasa"),
            _rr("ana2", 0.90, "anayasa"),
            _rr("yarg1", 0.30, "yargitay"),
        ]
    monkeypatch.setattr(emsal_mod, "search_with_rerank", fake_rerank)
    out = await emsal_mod.emsal_node({"question": "işten çıkarıldım", "domain": "isHukuku"})
    refs = out["emsal_refs"]
    # İlk emsal Yargıtay olmalı (anayasa hacim baskısı kırıldı)
    assert refs[0]["source_id"] == "yarg1"
