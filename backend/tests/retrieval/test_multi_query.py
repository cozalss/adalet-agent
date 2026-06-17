"""multi_query — paraphrase expansion + RRF fan-out testleri.

Sprint-4 W1: JSON-mode enforce. MockLLM artık {"paraphrases": [...]} döner;
_parse_json_paraphrases primary, _parse_numbered fallback. Her iki yol da
test edilir.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from retrieval import multi_query as mq
from retrieval.hybrid_search import SearchResult

# --------------------------------------------------------------------------
# _parse_json_paraphrases (Sprint-4 W1 primary)
# --------------------------------------------------------------------------


def test_parse_json_paraphrases_basic():
    raw = '{"paraphrases": ["soru 1", "soru 2", "soru 3"]}'
    out = mq._parse_json_paraphrases(raw, max_n=5)
    assert out == ["soru 1", "soru 2", "soru 3"]


def test_parse_json_paraphrases_with_fence():
    raw = '```json\n{"paraphrases": ["a soru", "b soru"]}\n```'
    out = mq._parse_json_paraphrases(raw, max_n=5)
    assert out == ["a soru", "b soru"]


def test_parse_json_paraphrases_caps_at_max_n():
    raw = '{"paraphrases": ["a soru", "b soru", "c soru", "d soru"]}'
    out = mq._parse_json_paraphrases(raw, max_n=2)
    assert len(out) == 2


def test_parse_json_paraphrases_invalid_returns_empty():
    assert mq._parse_json_paraphrases("not json at all", max_n=5) == []
    assert mq._parse_json_paraphrases("", max_n=5) == []


def test_parse_json_paraphrases_skips_short_and_non_str():
    raw = '{"paraphrases": ["ok", "valid uzun soru", 42, null, "x"]}'
    out = mq._parse_json_paraphrases(raw, max_n=5)
    # "ok" ve "x" çok kısa (5 char altı), 42 ve null str değil → atılır
    assert out == ["valid uzun soru"]


def test_parse_json_paraphrases_recovers_from_surrounding_text():
    """LLM zaman zaman JSON'u açıklama ile sarıyor — { ... } bloğunu çıkar."""
    raw = 'İşte cevap:\n{"paraphrases": ["a soru", "b soru"]}\nBu kadar.'
    out = mq._parse_json_paraphrases(raw, max_n=5)
    assert out == ["a soru", "b soru"]


# --------------------------------------------------------------------------
# _parse_numbered (fallback)
# --------------------------------------------------------------------------


def test_parse_numbered_basic():
    raw = (
        "1. Birinci paraphrase\n"
        "2. İkinci paraphrase\n"
        "3. Üçüncü paraphrase"
    )
    out = mq._parse_numbered(raw, max_n=5)
    assert len(out) == 3
    assert "Birinci paraphrase" in out
    assert "İkinci paraphrase" in out


def test_parse_numbered_with_dash_prefix():
    raw = "- ilk paraphrase\n- ikinci paraphrase\n- üçüncü paraphrase"
    out = mq._parse_numbered(raw, max_n=5)
    assert len(out) == 3


def test_parse_numbered_caps_at_max_n():
    raw = "\n".join(f"{i}. line{i}" for i in range(1, 11))
    out = mq._parse_numbered(raw, max_n=3)
    assert len(out) == 3


def test_parse_numbered_handles_empty():
    assert mq._parse_numbered("", max_n=5) == []
    assert mq._parse_numbered("   ", max_n=5) == []


def test_parse_numbered_skips_short_lines():
    raw = "1. ok\n2. valid line here\n3. x"
    out = mq._parse_numbered(raw, max_n=5)
    # 'ok' ve 'x' çok kısa (5 char altı) → atılır
    assert len(out) == 1
    assert "valid line here" in out


# --------------------------------------------------------------------------
# expand_queries — MockLLM ile entegrasyon
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expand_queries_single_returns_original():
    """n<=1 → sadece orijinal döner, LLM çağırılmaz."""
    mq.reset_cache()
    queries = await mq.expand_queries("Kıdem tazminatı", n=1)
    assert queries == ["Kıdem tazminatı"]


@pytest.mark.asyncio
async def test_expand_queries_returns_at_least_original():
    """MockLLM dummy döner → en azından orijinal sorgu listede."""
    mq.reset_cache()
    queries = await mq.expand_queries("Kıdem tazminatı nasıl hesaplanır?", n=3)
    assert queries[0] == "Kıdem tazminatı nasıl hesaplanır?"
    assert len(queries) >= 1


@pytest.mark.asyncio
async def test_expand_queries_json_mode_yields_multiple_paraphrases():
    """Sprint-4 W1: MockLLM JSON-mode'da paraphrases üretir → N elemanlı liste."""
    mq.reset_cache()
    queries = await mq.expand_queries(
        "Kira sözleşmesi feshi nasıl yapılır?", n=5, domain="kira",
    )
    # Orijinal + MockLLM'in stub paraphrase'leri → en az 2 farklı sorgu
    assert queries[0] == "Kira sözleşmesi feshi nasıl yapılır?"
    assert len(queries) >= 2
    # Tüm sorgular unique
    assert len(queries) == len(set(queries))


@pytest.mark.asyncio
async def test_expand_queries_cache_hit():
    """Aynı (question, domain, n) — ikinci çağrı LLM'siz cache'ten döner."""
    mq.reset_cache()
    q = "Test sorusu uzun bir hukuk sorusu"
    out1 = await mq.expand_queries(q, n=3, domain="isHukuku")
    # call_count'u ezbere bilmiyoruz — sadece tutarlılık
    out2 = await mq.expand_queries(q, n=3, domain="isHukuku")
    assert out1 == out2


@pytest.mark.asyncio
async def test_expand_queries_empty_input():
    out = await mq.expand_queries("", n=3)
    assert out == [""]


@pytest.mark.asyncio
async def test_expand_queries_reserves_slot_for_typo_variant(monkeypatch):
    """Typo varsa deterministic variant LLM'e gitmeden arama kolu olur."""
    mq.reset_cache()

    class _UnexpectedLLM:
        async def chat(self, **_kwargs):
            raise AssertionError("LLM should not be called when typo variant fills n=2")

    monkeypatch.setattr(mq, "get_llm", lambda: _UnexpectedLLM())
    queries = await mq.expand_queries("kidem tazmnatı", n=2, domain="isHukuku")

    assert queries[0] == "kidem tazmnatı"
    assert len(queries) == 2
    assert "kıdem tazminatı" in queries[1]


# --------------------------------------------------------------------------
# Hukuki eşanlam genişletmesi entegrasyonu (W15)
# --------------------------------------------------------------------------


class _FailingLLM:
    """chat() ConnectionError fırlatır → multi_query deterministic fallback."""

    async def chat(self, **_kwargs):
        raise ConnectionError("simulated llm down")


class _OneParaLLM:
    """chat() tek paraphrase döner → success path boş slot doldurma tetiklenir."""

    async def chat(self, **_kwargs):
        return SimpleNamespace(content='{"paraphrases": ["tek bir uzun paraphrase cümlesi"]}')


@pytest.mark.asyncio
async def test_fallback_includes_legal_synonyms(monkeypatch):
    """LLM down → eşanlam + morfoloji deterministic fallback; eşanlam varyantı gelir."""
    mq.reset_cache()
    monkeypatch.setattr(mq, "get_llm", lambda: _FailingLLM())
    queries = await mq.expand_queries("depozito iade edilmedi ev sahibi vermiyor", n=5)
    assert queries[0] == "depozito iade edilmedi ev sahibi vermiyor"
    joined = " || ".join(queries)
    # depozito veya ev sahibi grubundan en az bir eşanlam ikamesi
    assert any(
        s in joined
        for s in ("güvence bedeli", "kira teminatı", "kiraya veren", "mülk sahibi")
    )


@pytest.mark.asyncio
async def test_success_path_fills_remaining_slots_with_synonyms(monkeypatch):
    """LLM az paraphrase üretirse kalan slot'lar eşanlamla dolar (displacement YOK)."""
    mq.reset_cache()
    monkeypatch.setattr(mq, "get_llm", lambda: _OneParaLLM())
    queries = await mq.expand_queries("depozito iade edilmedi", n=5)
    assert queries[0] == "depozito iade edilmedi"
    # LLM paraphrase korunmalı
    assert "tek bir uzun paraphrase cümlesi" in queries
    # Boş slot'lar eşanlamla dolduruldu → 2'den fazla
    assert len(queries) > 2
    assert len(queries) == len(set(queries))  # benzersiz


@pytest.mark.asyncio
async def test_synonym_expansion_disabled_via_flag(monkeypatch):
    """LEGAL_SYNONYM_EXPANSION=0 → fallback yalnız morfoloji, eşanlam yok."""
    mq.reset_cache()
    monkeypatch.setattr(mq, "LEGAL_SYNONYM_ENABLED", False)
    monkeypatch.setattr(mq, "get_llm", lambda: _FailingLLM())
    queries = await mq.expand_queries("depozito iade edilmedi", n=5)
    joined = " || ".join(queries)
    assert "güvence bedeli" not in joined and "kira teminatı" not in joined


# --------------------------------------------------------------------------
# fan_out_search — RRF merge logic
# --------------------------------------------------------------------------


def _sr(chunk_id: str, score: float = 1.0) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id, score=score, text=f"text-{chunk_id}",
        source="test", source_url="http://test", domain="test", metadata={},
    )


# --- rrf_merge (paylaşılan RRF — fan_out + speculative tek kaynak) ---

def test_rrf_merge_boosts_common_high_rank():
    """İki listede de üst-sırada olan chunk en yüksek RRF skorunu alır (concat değil)."""
    l1 = [_sr("A"), _sr("B"), _sr("C")]   # A@0, B@1
    l2 = [_sr("B"), _sr("D"), _sr("A")]   # B@0, A@2
    out = mq.rrf_merge([l1, l2], top_k=4)
    ids = [r.chunk_id for r in out]
    # B: 1/61+1/60 > A: 1/60+1/62 → B ilk sırada (ortak isabet + ikisinde de üstte)
    assert ids[0] == "B"
    assert set(ids) == {"A", "B", "C", "D"}


def test_rrf_merge_score_is_fused_rrf():
    out = mq.rrf_merge([[_sr("X", score=0.99)]], top_k=1)
    assert out[0].score == pytest.approx(1.0 / mq.RRF_K)  # orijinal 0.99 değil, RRF skoru


def test_rrf_merge_empty_and_top_k():
    assert mq.rrf_merge([], top_k=5) == []
    assert mq.rrf_merge([[]], top_k=5) == []
    out = mq.rrf_merge([[_sr(c) for c in "ABCDE"]], top_k=2)
    assert len(out) == 2


@pytest.mark.asyncio
async def test_fan_out_search_rrf_merges_overlap(monkeypatch):
    """Iki sorgu farklı sıralar — RRF birleştirir, overlap yüksek skor alır."""
    # search() mock: query'ye göre farklı sonuç
    async def fake_search(question, top_k=5, prefetch_limit=50, domain=None, sparse_domain=None, doc_type=None):
        if "q1" in question:
            return [_sr("A"), _sr("B"), _sr("C")]
        if "q2" in question:
            return [_sr("B"), _sr("D"), _sr("A")]  # A ve B overlap
        return []

    monkeypatch.setattr(mq, "search", fake_search)
    merged = await mq.fan_out_search(["q1", "q2"], top_k=4)
    ids = [m.chunk_id for m in merged]
    # B her ikisinde de üst sırada → en yüksek RRF
    # A her ikisinde de var ama daha aşağı
    assert "B" in ids
    assert "A" in ids
    assert ids[0] in {"A", "B"}  # overlap'ler ilk sıra


@pytest.mark.asyncio
async def test_fan_out_search_empty_queries():
    assert await mq.fan_out_search([], top_k=5) == []


@pytest.mark.asyncio
async def test_fan_out_search_forwards_sparse_domain(monkeypatch):
    """KIRMIZI METRİK (denetim 2026-06-04): sparse_domain HER alt-sorguya iletilmeli →
    trafik/icra MQ alt-sorguları BGE-M3 BM25 sparse'ı kaybetmez."""
    seen: list[str | None] = []

    async def spy_search(question, top_k=5, prefetch_limit=50, domain=None, sparse_domain=None, doc_type=None):
        seen.append(sparse_domain)
        return [_sr("A")]

    monkeypatch.setattr(mq, "search", spy_search)
    await mq.fan_out_search(["q1", "q2", "q3"], top_k=4, sparse_domain="trafik")
    assert seen == ["trafik", "trafik", "trafik"]  # tüm alt-sorgular sparse hint aldı


@pytest.mark.asyncio
async def test_fan_out_search_forwards_doc_type(monkeypatch):
    """doc_type HER alt-sorguya iletilir → mevzuat law-filtresi MQ alt-sorgularında da geçerli
    (denetim 2026-06-04: query-time law filtre +15.8pp madde_recall@5)."""
    seen: list[str | None] = []

    async def spy(question, top_k=5, prefetch_limit=50, domain=None, sparse_domain=None, doc_type=None):
        seen.append(doc_type)
        return [_sr("A")]

    monkeypatch.setattr(mq, "search", spy)
    await mq.fan_out_search(["q1", "q2"], top_k=4, doc_type="law")
    assert seen == ["law", "law"]


@pytest.mark.asyncio
async def test_fan_out_search_handles_query_failure(monkeypatch):
    """Bir sorgu exception fırlatsa diğerleri devam etmeli."""
    async def flaky_search(question, top_k=5, prefetch_limit=50, domain=None, sparse_domain=None, doc_type=None):
        if "fail" in question:
            raise RuntimeError("simulated qdrant down")
        return [_sr("X"), _sr("Y")]

    monkeypatch.setattr(mq, "search", flaky_search)
    merged = await mq.fan_out_search(["good", "fail", "good2"], top_k=5)
    ids = {m.chunk_id for m in merged}
    assert "X" in ids and "Y" in ids
