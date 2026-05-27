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


# --------------------------------------------------------------------------
#  _merge_dedup — domain-scoped takviye sonuçlarını birleştirme
# --------------------------------------------------------------------------

def test_merge_dedup_removes_duplicate_chunk_ids():
    primary = [_sr("X", 0.9, kanun_kodu="TKHK"), _sr("Y", 0.8, kanun_kodu="TBK")]
    secondary = [_sr("Y", 0.3, kanun_kodu="TBK"), _sr("Z", 0.2, kanun_kodu="TTK")]
    out = mevzuat_mod._merge_dedup(primary, secondary)
    ids = [r.chunk_id for r in out]
    assert ids == ["X", "Y", "Z"]  # Y tek kez, primary'den


def test_merge_dedup_primary_score_wins():
    primary = [_sr("Y", 0.9, kanun_kodu="TKHK")]      # domain-scoped, güvenilir
    secondary = [_sr("Y", 0.1, kanun_kodu="TKHK")]    # genel arama, düşük skor
    out = mevzuat_mod._merge_dedup(primary, secondary)
    assert len(out) == 1
    assert out[0].score == pytest.approx(0.9)  # primary korunur


# --------------------------------------------------------------------------
#  _domain_priority_rerank — cross-encoder sırasını domain-önceliğiyle birleştir
# --------------------------------------------------------------------------

def test_domain_priority_promotes_primary_kanun():
    """Cross-encoder TTK'yı öne koysa bile birincil kanun TKHK tier-0'a çıkar.

    Buzdolabı bug'ı: cross-encoder TTK taşıma maddesini (878) TKHK ayıplı-mal
    maddesinin (11) üstüne koyuyordu. Tier sort TKHK'yı başa alır.
    """
    cands = [
        _sr("ttk878", 0.95, kanun_kodu="TTK"),   # cross-encoder #1 (alakasız taşıma)
        _sr("tkhk88", 0.80, kanun_kodu="TKHK"),  # tüketici
        _sr("ttk874", 0.70, kanun_kodu="TTK"),
        _sr("tkhk11", 0.40, kanun_kodu="TKHK"),  # ASIL madde, cross-encoder geride
    ]
    out, n_primary = mevzuat_mod._domain_priority_rerank(cands, "tuketici")
    ids = [c.chunk_id for c in out]
    # Her iki TKHK, her iki TTK'nın önüne geçmeli
    assert ids[:2] == ["tkhk88", "tkhk11"]   # tier-0, cross-encoder sırasında
    assert ids[2:] == ["ttk878", "ttk874"]   # tier-1 (TTK tüketici domain'inde ama ikincil)
    assert n_primary == 2


def test_domain_priority_preserves_cross_encoder_order_within_tier():
    """Aynı tier içinde cross-encoder (giriş) sırası korunur — stable sort."""
    cands = [
        _sr("a", 0.9, kanun_kodu="TKHK"),
        _sr("b", 0.8, kanun_kodu="TKHK"),
        _sr("c", 0.7, kanun_kodu="TKHK"),
    ]
    out, n_primary = mevzuat_mod._domain_priority_rerank(cands, "tuketici")
    assert [c.chunk_id for c in out] == ["a", "b", "c"]
    assert n_primary == 3


def test_domain_priority_off_domain_sinks_to_last_tier():
    """Domain dışı kanun (KTK trafik) tüketici sorgusunda en sona iner."""
    cands = [
        _sr("ktk", 0.99, kanun_kodu="KTK"),      # domain dışı, en yüksek skor
        _sr("tbk", 0.50, kanun_kodu="TBK"),      # tüketici ikincil (tier-1)
        _sr("tkhk", 0.40, kanun_kodu="TKHK"),    # tüketici birincil (tier-0)
    ]
    out, _ = mevzuat_mod._domain_priority_rerank(cands, "tuketici")
    assert [c.chunk_id for c in out] == ["tkhk", "tbk", "ktk"]


def test_domain_priority_unknown_domain_noop():
    cands = [_sr("a", 0.5, kanun_kodu="TTK"), _sr("b", 0.4, kanun_kodu="TKHK")]
    out, n_primary = mevzuat_mod._domain_priority_rerank(cands, "unknown")
    assert out == cands
    assert n_primary == 0


# --------------------------------------------------------------------------
#  Cross-encoder rerank entegrasyonu (fake reranker — model yüklenmez)
# --------------------------------------------------------------------------

class _FakeReranked:
    """RerankResult-benzeri — mevzuat_node'un eriştiği alanlar."""

    def __init__(self, sr: SearchResult, score: float) -> None:
        self.chunk_id = sr.chunk_id
        self.score = score
        self.text = sr.text
        self.source = sr.source
        self.source_url = sr.source_url
        self.domain = sr.domain
        self.metadata = sr.metadata


class _FakeReranker:
    """Alaka sırası: TKHK > diğerleri (RRF skorunun TERSİ) — alakayı taklit eder."""

    def rerank(self, query, candidates, top_k):
        ordered = sorted(
            candidates,
            key=lambda c: 0 if c.metadata.get("kanun_kodu") == "TKHK" else 1,
        )
        return [_FakeReranked(c, 0.99 - i * 0.1) for i, c in enumerate(ordered[:top_k])]


def _plain_search_env(monkeypatch):
    """HyDE/MQ kapat → düz `search` yolu; rerank aç; çapa-fetch'i boşla.

    `fetch_maddeler` boş döndürülür ki anchor merge bu testlerin (rerank/boost)
    çıktısını kirletmesin — çapa mantığı kendi testlerinde ayrıca sınanır.
    """
    monkeypatch.setattr(mevzuat_mod, "HYDE_ENABLED", False)
    monkeypatch.setattr(mevzuat_mod, "MULTI_QUERY_ENABLED", False)
    monkeypatch.setattr(mevzuat_mod, "MEVZUAT_RERANK_ENABLED", True)

    async def _no_anchors(pairs):
        return []

    monkeypatch.setattr(mevzuat_mod, "fetch_maddeler", _no_anchors)


@pytest.mark.asyncio
async def test_mevzuat_rerank_promotes_relevant_over_noise(monkeypatch):
    """Yüksek RRF skorlu alakasız TTK, düşük skorlu alakalı TKHK'nın altına
    iner — cross-encoder gerçek alakayı yansıtır."""
    _plain_search_env(monkeypatch)
    cands = [
        _sr("noise", 0.95, kanun_kodu="TTK"),     # yüksek RRF ama alakasız
        _sr("relevant", 0.05, kanun_kodu="TKHK"),  # düşük RRF ama alakalı
    ]

    async def _fake_search(question, top_k=5, domain=None, **kw):
        return cands

    monkeypatch.setattr(mevzuat_mod, "search", _fake_search)
    monkeypatch.setattr(mevzuat_mod, "get_reranker", lambda: _FakeReranker())

    out = await mevzuat_mod.mevzuat_node({"question": "buzdolabı ayıplı", "domain": "tuketici"})
    refs = out["mevzuat_refs"]
    assert refs[0]["source_id"] == "relevant"  # TKHK rerank ile başa çıktı


@pytest.mark.asyncio
async def test_mevzuat_combines_hyde_and_multi_query(monkeypatch):
    """HyDE ve multi-query birlikte açıksa iki aday havuzu da final'e girmeli."""
    monkeypatch.setattr(mevzuat_mod, "HYDE_ENABLED", True)
    monkeypatch.setattr(mevzuat_mod, "MULTI_QUERY_ENABLED", True)
    monkeypatch.setattr(mevzuat_mod, "MEVZUAT_DOMAIN_FILTER_ENABLED", False)
    monkeypatch.setattr(mevzuat_mod, "MEVZUAT_RERANK_ENABLED", False)

    async def _fake_hyde(question, **kw):
        return [_sr("hyde-hit", 0.9, kanun_kodu="TKHK")]

    async def _fake_mq(question, **kw):
        return [_sr("mq-hit", 0.8, kanun_kodu="TBK")]

    async def _unexpected_search(*args, **kwargs):
        raise AssertionError("hybrid fallback çağrılmamalı")

    monkeypatch.setattr(mevzuat_mod, "search_with_hyde", _fake_hyde)
    monkeypatch.setattr(mevzuat_mod, "search_multi_query", _fake_mq)
    monkeypatch.setattr(mevzuat_mod, "search", _unexpected_search)

    out = await mevzuat_mod.mevzuat_node({"question": "ayıplı ürün", "domain": "tuketici"})
    ids = {r["source_id"] for r in out["mevzuat_refs"]}

    assert {"hyde-hit", "mq-hit"}.issubset(ids)


@pytest.mark.asyncio
async def test_mevzuat_rerank_disabled_keeps_search_order(monkeypatch):
    _plain_search_env(monkeypatch)
    monkeypatch.setattr(mevzuat_mod, "MEVZUAT_RERANK_ENABLED", False)
    cands = [_sr("first", 0.95, kanun_kodu="TTK"), _sr("second", 0.05, kanun_kodu="TKHK")]

    async def _fake_search(question, top_k=5, domain=None, **kw):
        return cands

    monkeypatch.setattr(mevzuat_mod, "search", _fake_search)
    out = await mevzuat_mod.mevzuat_node({"question": "x", "domain": "tuketici"})
    assert [r["source_id"] for r in out["mevzuat_refs"]] == ["first", "second"]


@pytest.mark.asyncio
async def test_mevzuat_rerank_failure_falls_back_gracefully(monkeypatch):
    _plain_search_env(monkeypatch)
    cands = [_sr("a", 0.9, kanun_kodu="TKHK"), _sr("b", 0.5, kanun_kodu="TBK")]

    async def _fake_search(question, top_k=5, domain=None, **kw):
        return cands

    class _BoomReranker:
        def rerank(self, *a, **k):
            raise RuntimeError("reranker çöktü")

    monkeypatch.setattr(mevzuat_mod, "search", _fake_search)
    monkeypatch.setattr(mevzuat_mod, "get_reranker", lambda: _BoomReranker())
    out = await mevzuat_mod.mevzuat_node({"question": "x", "domain": "tuketici"})
    # çökse de search sırası korunur (graceful degrade)
    assert [r["source_id"] for r in out["mevzuat_refs"]] == ["a", "b"]


# --------------------------------------------------------------------------
#  _ensure_core_in_topk — çapa maddelerini final top-K'da GARANTİ et
# --------------------------------------------------------------------------

def test_ensure_core_no_anchors_is_plain_slice():
    """anchor_ids boşsa düz ranked[:top_k] — davranış değişmez."""
    ranked = [_sr(c, 0.0) for c in ("a", "b", "c", "d")]
    out = mevzuat_mod._ensure_core_in_topk(ranked, set(), top_k=2)
    assert [r.chunk_id for r in out] == ["a", "b"]


def test_ensure_core_pulls_anchor_into_topk():
    """Çapa madde ranked'da top_k DIŞINDA ise yine de final'a girer."""
    ranked = [_sr(c, 0.0) for c in ("noise1", "noise2", "noise3", "anchor")]
    out = mevzuat_mod._ensure_core_in_topk(ranked, {"anchor"}, top_k=2)
    ids = [r.chunk_id for r in out]
    assert "anchor" in ids
    assert len(ids) == 2


def test_ensure_core_preserves_ranked_order():
    """Seçilenler ranked sırasında döner (çapa öne zorlanmaz, sadece dahil edilir)."""
    ranked = [_sr(c, 0.0) for c in ("a", "b", "anchor", "d")]
    out = mevzuat_mod._ensure_core_in_topk(ranked, {"anchor"}, top_k=3)
    # a, b, anchor seçilir; ranked sırasında: a < b < anchor
    assert [r.chunk_id for r in out] == ["a", "b", "anchor"]


def test_ensure_core_multiple_anchors_all_included():
    """Birden çok çapa + dar top_k → çapalar önceliklenir, ranked sırasıyla."""
    ranked = [_sr(c, 0.0) for c in ("x", "anc1", "y", "anc2", "z")]
    out = mevzuat_mod._ensure_core_in_topk(ranked, {"anc1", "anc2"}, top_k=2)
    assert {r.chunk_id for r in out} == {"anc1", "anc2"}


def test_ensure_core_anchor_already_in_topk_no_dup():
    """Çapa zaten top_k içindeyse tekrar eklenmez (dedup)."""
    ranked = [_sr(c, 0.0) for c in ("anchor", "b", "c")]
    out = mevzuat_mod._ensure_core_in_topk(ranked, {"anchor"}, top_k=2)
    ids = [r.chunk_id for r in out]
    assert ids == ["anchor", "b"]
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------
#  Çapa entegrasyonu — fetch_maddeler ile kilit maddeler havuza GARANTİ girer
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anchor_madde_guaranteed_in_output(monkeypatch):
    """İş Hukuku ihbar maddesi (İK m.17) cross-encoder onu sıralamadan düşürse
    bile çapa-fetch ile final çıktıda görünür."""
    monkeypatch.setattr(mevzuat_mod, "HYDE_ENABLED", False)
    monkeypatch.setattr(mevzuat_mod, "MULTI_QUERY_ENABLED", False)
    monkeypatch.setattr(mevzuat_mod, "MEVZUAT_RERANK_ENABLED", False)
    # Çapa mantığı domain-filter bayrağına bağlı; conftest test'te kapatır,
    # production'da "1" (açık). Bu testte gerçek prod davranışını sınamak için açıyoruz.
    monkeypatch.setattr(mevzuat_mod, "MEVZUAT_DOMAIN_FILTER_ENABLED", True)

    # search çapayı DÖNDÜRMEZ — sadece alakasız gürültü
    noise = [_sr(f"noise{i}", 0.9 - i * 0.1, kanun_kodu="DMK") for i in range(5)]

    async def _fake_search(question, top_k=5, domain=None, **kw):
        return noise

    # fetch_maddeler İK m.17'yi (ihbar) çapa olarak döndürür
    anchor = _sr("m-IK-17", 0.0, kanun_kodu="IK")

    async def _fake_anchors(pairs):
        return [anchor]

    monkeypatch.setattr(mevzuat_mod, "search", _fake_search)
    monkeypatch.setattr(mevzuat_mod, "fetch_maddeler", _fake_anchors)

    out = await mevzuat_mod.mevzuat_node({"question": "işten atıldım", "domain": "isHukuku"})
    ids = [r["source_id"] for r in out["mevzuat_refs"]]
    assert "m-IK-17" in ids  # çapa GARANTİ final'da
