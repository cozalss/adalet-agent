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


def test_sayistay_and_danistay_preferred_for_idari():
    """İdari domain'de Sayıştay + Danıştay tier-0; Yargıtay tier-1; anayasa tier-2.

    Regresyon: Sayıştay corpus'ta var (231) ama emsal kaynak setinde DEĞİLDİ → hiç
    yüzeye çıkmıyordu (2026-06-04 fix). Artık idari/vergi'de öncelikli emsal."""
    cases = [
        _rr("ana", 0.99, "anayasa"),
        _rr("yarg", 0.70, "yargitay"),
        _rr("say", 0.40, "sayistay"),
        _rr("dan", 0.30, "danistay"),
    ]
    out, n_pref = emsal_mod._court_priority_sort(cases, "idari")
    ids = [c.chunk_id for c in out]
    assert ids[:2] == ["say", "dan"]  # tier-0 (cross-encoder sırasında say>dan)
    assert ids[2] == "yarg"           # tier-1
    assert ids[3] == "ana"            # tier-2
    assert n_pref == 2


def test_case_sources_includes_decision_courts():
    """Karar kaynak seti corpus'taki TÜM mahkemeleri içermeli — sayistay eksikse
    doc_type=None olduğu için sessizce filtrelenir (gerçek bug'dı)."""
    assert {"sayistay", "danistay", "anayasa", "yargitay", "uyap", "gib_ozelge"} <= emsal_mod._CASE_SOURCES


def test_domain_without_preference_is_noop():
    """DOMAIN_PREFERRED_COURTS'ta olmayan domain → sıra değişmez."""
    cases = [_rr("a", 0.9, "anayasa"), _rr("b", 0.4, "yargitay")]
    out, n_pref = emsal_mod._court_priority_sort(cases, "bilinmeyen")
    assert [c.chunk_id for c in out] == ["a", "b"]
    assert n_pref == 0


# --- daire alt-tier (P9, 2026-06-11) ---

def _rr_ch(chunk_id: str, score: float, chamber: str) -> emsal_mod.RerankResult:
    rr = _rr(chunk_id, score, "yargitay")
    rr.metadata["chamber"] = chamber
    return rr


def test_chamber_subtier_promotes_consumer_chambers():
    """tuketici: 13. HD/3. HD/HGK, hacim-baskın 11. HD'nin ÜSTÜNE çıkar (court-tier içinde)."""
    cases = [
        _rr_ch("hd11_a", 0.9, "11. Hukuk Dairesi"),
        _rr_ch("hd11_b", 0.8, "11. Hukuk Dairesi"),
        _rr_ch("hd13", 0.5, "13. Hukuk Dairesi"),
        _rr_ch("hgk", 0.3, "Hukuk Genel Kurulu"),
    ]
    out, _ = emsal_mod._court_priority_sort(cases, "tuketici")
    assert [c.chunk_id for c in out] == ["hd13", "hgk", "hd11_a", "hd11_b"]
    # alt-tier içinde CE sırası korunur (hd13 0.5 > hgk 0.3; hd11_a 0.9 > hd11_b 0.8)


def test_chamber_subtier_only_for_configured_domains():
    """Daire tercihi tanımlı OLMAYAN domain'de (kira) sıra court-tier'la aynı kalır."""
    cases = [
        _rr_ch("hd11", 0.9, "11. Hukuk Dairesi"),
        _rr_ch("hd13", 0.5, "13. Hukuk Dairesi"),
    ]
    out, _ = emsal_mod._court_priority_sort(cases, "kira")
    assert [c.chunk_id for c in out] == ["hd11", "hd13"]  # CE sırası bozulmaz


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


# --- CRAG canlı fallback (opt-in) ---

async def _no_scoped(monkeypatch):
    async def fake_search(**_k):
        return []
    monkeypatch.setattr(emsal_mod, "search", fake_search)


@pytest.mark.asyncio
async def test_live_fallback_off_by_default(monkeypatch):
    """Flag kapali + zayif corpus → canli fallback CAGRILMAZ (baseline)."""
    monkeypatch.delenv("EMSAL_LIVE_FALLBACK_ENABLED", raising=False)
    async def fake_rerank(question, top_k=5, candidates_n=20, domain=None):
        return [_rr("c1", 0.10, "yargitay")]  # zayif
    monkeypatch.setattr(emsal_mod, "search_with_rerank", fake_rerank)
    await _no_scoped(monkeypatch)
    called = {"live": False}
    async def fake_live(*_a, **_k):
        called["live"] = True
        return []
    monkeypatch.setattr(emsal_mod, "fetch_and_rank_live", fake_live)
    out = await emsal_mod.emsal_node({"question": "x", "domain": "trafik"})
    assert called["live"] is False
    assert out["emsal_refs"][0]["source_id"] == "c1"


@pytest.mark.asyncio
async def test_live_fallback_triggers_on_weak_corpus(monkeypatch):
    """Flag acik + zayif corpus → internetten cekilen (canli) emsal ONE eklenir."""
    monkeypatch.setenv("EMSAL_LIVE_FALLBACK_ENABLED", "1")
    # Bu test live-fallback mantığını izole eder; typo-variant dalı (fan_out_search
    # gerçek corpus'a vurup mock'u bypass eder → zayıf-corpus senaryosu bozulur) kapatılır.
    monkeypatch.setenv("TYPO_TOLERANCE_ENABLED", "0")
    async def fake_rerank(question, top_k=5, candidates_n=20, domain=None):
        return [_rr("c1", 0.10, "yargitay")]
    monkeypatch.setattr(emsal_mod, "search_with_rerank", fake_rerank)
    await _no_scoped(monkeypatch)
    from retrieval.hybrid_search import SearchResult
    async def fake_live(question, domain, **_k):
        return [SearchResult("live1", 0.9, "canli trafik dava metni",
                             "sigorta_tahkim", "http://x", domain, {"live": True})]
    monkeypatch.setattr(emsal_mod, "fetch_and_rank_live", fake_live)
    out = await emsal_mod.emsal_node({"question": "trafik kazasi", "domain": "trafik"})
    refs = out["emsal_refs"]
    assert refs[0]["source_id"] == "live1"
    assert "canlı" in refs[0]["title"]


@pytest.mark.asyncio
async def test_live_fallback_skips_on_strong_corpus(monkeypatch):
    """Flag acik AMA corpus GUCLU → canli fallback gereksiz, cagrilmaz.

    CRAG-redesign (2026-06-10): 'guclu' artik yuksek CE skoru DEGIL, sorgu
    kelimelerinin donen kararlarca KAPSANMASI (coverage modu, olculmus karar —
    skor-esigi 24/24 yanlis-alarm vermisti). Soru kelimeleri chunk metninde
    geciyor → coverage 1.0 → tetikleme yok (skor dusuk olsa bile).
    """
    monkeypatch.setenv("EMSAL_LIVE_FALLBACK_ENABLED", "1")
    async def fake_rerank(question, top_k=5, candidates_n=20, domain=None):
        return [_rr("c1", 0.10, "yargitay")]  # text: "karar metni c1" — soruyu kapsar
    monkeypatch.setattr(emsal_mod, "search_with_rerank", fake_rerank)
    await _no_scoped(monkeypatch)
    called = {"live": False}
    async def fake_live(*_a, **_k):
        called["live"] = True
        return []
    monkeypatch.setattr(emsal_mod, "fetch_and_rank_live", fake_live)
    out = await emsal_mod.emsal_node({"question": "karar metni", "domain": "trafik"})
    assert called["live"] is False
    assert out["emsal_refs"][0]["source_id"] == "c1"
