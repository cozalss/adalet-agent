"""Multi-Query Expansion — N adet paraphrase üret, paralel ara, RRF merge.

Vatandaş hukuk dilini sürekli farklı şekillerde sorar:
  "depozitomu vermiyor"
  "kira teminatı geri ödenmedi"
  "ev sahibim güvence parasını iade etmiyor"

Hepsi aynı semantik soru. Tek sorgu retrieval semantic gap'i kapatamaz.

Bu modül LLM ile N=3..5 farklı reformülasyon üretir, her birini ayrı arar,
sonra **Reciprocal Rank Fusion (RRF)** ile birleştirir. Recall@20 +6pp etki
beklenir (RAG literatür).

Cache: aynı (question, domain) çağrısı 1 saat in-memory LRU'da tutulur.

Akış:
    1) expand_queries(q, n=5) → JSON-mode LLM → ["q paraphrase 1", "q2", "q3", "q4"]
       (+orijinal soru). Sprint-4 W1: JSON mode enforce — regex parse silent
       degradation bug'ını (Roma rakamı, "•" prefix vb.) önler.
    2) Orijinal soru + paraphrase'ler → fan-out search (paralel)
    3) RRF score = sum(1 / (rank + k))   # k env-toggle (default 60)
    4) Top-K sort ve dön
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import OrderedDict
from dataclasses import dataclass

import httpx
import structlog

from agents.llm import ChatMessage, get_llm
from retrieval.hybrid_search import SearchResult, search
from retrieval.turkish_text import expand_with_synonyms, morphological_variants
from retrieval.typo_tolerance import typo_retrieval_variants

log = structlog.get_logger()

# --- Konfigürasyon ---
# Sprint-4 W1: 4 → 5. Literatürde N=5-8 standard; +Recall@20 beklentisi.
DEFAULT_N = int(os.getenv("MULTI_QUERY_N", "5"))
# Sprint-4 W1: RRF k env-toggle. Hafta 1.6 sweep'i için config edilebilir.
# Türkçe hukuk için 60 (standart) vs 80 (geç-rank'lara şans) sweep edilecek.
RRF_K = int(os.getenv("RRF_K", "60"))
MQ_CACHE_SIZE = 256                       # in-mem LRU max entry
# Deterministik hukuki eşanlam genişletmesi. LLM paraphrase'lerini ASLA
# atmaz — yalnız boş slot'ları doldurur ve LLM-fallback'i zenginleştirir.
# `LEGAL_SYNONYM_EXPANSION=0` ile kapatılır.
LEGAL_SYNONYM_ENABLED = os.getenv("LEGAL_SYNONYM_EXPANSION", "1").lower() in {"1", "true", "yes"}
# Sprint-4 W1: silent `except Exception` antipattern'i daraltıldı —
# CancelledError propagate olsun, gerçek bug'lar (TypeError vb.) yutulmasın.
_LLM_FALLBACK_EXCEPTIONS = (asyncio.TimeoutError, httpx.HTTPError, ConnectionError)
# Default 8s: Qwen 14B Q4 partial-offload (-ngl 20) ile 4 paraphrase üretmek
# ~5-7s sürüyor. Eski 3s default freeze_baseline v1_hyde ölçümünde tüm 50
# vakayı silent-timeout'a düşürüp multi_query'yi pratikte HYBRID'e degrede
# etti. 8s gerçek kazancı ölçmek için makul; hızlı LLM'lerle (CPU 7B) 3s
# yeterli, env ile override.
MQ_TIMEOUT_S = float(os.getenv("MULTI_QUERY_TIMEOUT_S", "8.0"))

# Sprint-4 W1: JSON-mode enforce. Eski numaralı regex parse silent fail
# yapıyordu (Roma rakamı, "•", iç-içe numara, LLM tutarsız format).
# JSON ile parse deterministic — ~15-20% vaka'da <2 paraphrase üretme
# problemi v0_vs_v1_DELTA.md'de gözlemlenmişti.
_PARAPHRASE_SYSTEM = (
    "Sen bir Türk hukuku terim asistanısın. Verilen vatandaş sorusunu "
    "AYNI ANLAMA gelen ama farklı kelimelerle yeniden yaz. Hedef: hukuki "
    "metin retrieval'ı için arama çeşitliliği. Madde no veya kanun adı "
    "UYDURMA — sadece dili çeşitlendir.\n\n"
    "Çıktı SADECE şu JSON formatında olsun, başka metin YOK:\n"
    '{"paraphrases": ["yeniden yazılmış soru 1", "yeniden yazılmış soru 2", ...]}'
)

_PARAPHRASE_USER = (
    "Hukuk alanı: {domain}\n"
    "Orijinal soru: {question}\n\n"
    "{n} farklı paraphrase üret. SADECE JSON nesnesi döndür."
)


# --------------------------------------------------------------------------
#  In-memory LRU cache (Redis Sprint-5'te eklenecek)
# --------------------------------------------------------------------------

_query_cache: OrderedDict[tuple[str, str, int, str], list[str]] = OrderedDict()


def _cache_get(key: tuple[str, str, int, str]) -> list[str] | None:
    if key in _query_cache:
        _query_cache.move_to_end(key)
        return list(_query_cache[key])
    return None


def _cache_put(key: tuple[str, str, int, str], val: list[str]) -> None:
    _query_cache[key] = val
    _query_cache.move_to_end(key)
    while len(_query_cache) > MQ_CACHE_SIZE:
        _query_cache.popitem(last=False)


def reset_cache() -> None:
    """Test ve cache invalidation için."""
    _query_cache.clear()


# --------------------------------------------------------------------------
#  Public: expand_queries
# --------------------------------------------------------------------------

async def expand_queries(
    question: str,
    n: int = DEFAULT_N,
    domain: str | None = None,
) -> list[str]:
    """Soruyu N farklı şekilde reformüle et. İlk öğe ORİJİNAL soru.

    LLM hata veya timeout durumunda sadece orijinal soruyla devam et.
    Cache: aynı (question, domain, n) için tekrar LLM çağrısı yok.
    """
    question = question.strip()
    if not question or n <= 1:
        return [question]

    typo_variants = typo_retrieval_variants(question, max_variants=max(0, n - 1))
    cache_key = (
        question.lower(),
        (domain or "").lower(),
        n,
        "|".join(typo_variants) if typo_variants else "-",
    )
    cached = _cache_get(cache_key)
    if cached:
        log.debug("mq_cache_hit", key=cache_key)
        return cached

    llm_slots = max(0, n - 1 - len(typo_variants))
    if llm_slots <= 0:
        out_queries = list(dict.fromkeys([question, *typo_variants]))[:n]
        _cache_put(cache_key, out_queries)
        return out_queries

    user_msg = _PARAPHRASE_USER.format(
        domain=domain or "genel hukuk", question=question, n=llm_slots,
    )

    llm = get_llm()
    try:
        resp = await asyncio.wait_for(
            llm.chat(
                messages=[
                    ChatMessage(role="system", content=_PARAPHRASE_SYSTEM),
                    ChatMessage(role="user", content=user_msg),
                ],
                temperature=0.4,
                max_tokens=400,
                json_mode=True,   # Sprint-4 W1: JSON-mode enforce
            ),
            timeout=MQ_TIMEOUT_S,
        )
    except _LLM_FALLBACK_EXCEPTIONS as exc:
        # Sprint-4 W1.5: LLM unavailable → Türkçe morfoloji deterministic
        # fallback (snowballstemmer). Orijinal soru + stem variants → en
        # azından morfo-genişletilmiş RRF arama yapılabilir.
        log.warning(
            "mq_llm_failed_morpho_fallback",
            error=str(exc) or type(exc).__name__,
            exc_type=type(exc).__name__,
        )
        # Hukuki eşanlam + morfoloji birlikte — LLM yokken en geniş deterministik
        # genişletme (eşanlam vatandaş↔jargon, morfoloji ek-çekim).
        budget = n - 1 - len(typo_variants)
        variants: list[str] = list(typo_variants)
        if LEGAL_SYNONYM_ENABLED:
            variants += expand_with_synonyms(question, max_variants=budget)
        variants += morphological_variants(question, max_variants=budget)
        out_queries = list(dict.fromkeys([question, *variants]))[:n]
        if len(out_queries) >= 2:
            _cache_put(cache_key, out_queries)
        return out_queries

    paraphrases = _parse_json_paraphrases(resp.content, max_n=llm_slots)
    # JSON parse silent-fallback: numaralı/markdown formatına düşer.
    if not paraphrases:
        log.debug("mq_json_parse_empty_fallback_to_numbered", raw=resp.content[:160])
        paraphrases = _parse_numbered(resp.content, max_n=llm_slots)
    # Boş çıkarsa orijinalle dön; çift ise tek tut
    queries = [question, *typo_variants] + [p for p in paraphrases if p and p != question]
    queries = list(dict.fromkeys(queries))[:n]

    # LLM az paraphrase ürettiyse (veya hiç) kalan slot'ları deterministik
    # hukuki eşanlamla DOLDUR — LLM paraphrase'leri asla atılmaz (displacement
    # yok). LLM zaten n slot'u doldurduysa bu no-op.
    if LEGAL_SYNONYM_ENABLED and len(queries) < n:
        for syn in expand_with_synonyms(question, max_variants=n - len(queries)):
            if syn not in queries:
                queries.append(syn)
            if len(queries) >= n:
                break

    _cache_put(cache_key, queries)
    log.info(
        "mq_expanded",
        n=len(queries),
        n_paraphrases=len(paraphrases),
        domain=domain,
    )
    return queries


# --------------------------------------------------------------------------
#  Public: fan_out_search
# --------------------------------------------------------------------------

@dataclass(slots=True)
class _Hit:
    """Internal: RRF accumulator."""

    sr: SearchResult
    rrf_score: float


def rrf_merge(
    result_lists: list[list[SearchResult]], top_k: int, k: int = RRF_K,
) -> list[SearchResult]:
    """Birden çok SIRALI sonuç listesini Reciprocal Rank Fusion ile birleştir.

    RANK-tabanlı (skor-ölçeği BAĞIMSIZ): her listede pozisyon → 1/(rank+k) katkısı; aynı chunk
    birden çok listede üst-sıradaysa skoru toplanır → ORTAK isabet öne çıkar. SearchResult.score
    fused-RRF skoruyla güncellenir (downstream tutarlılık). Farklı skor-ölçekli kaynakları
    (HyDE-RRF, MQ-RRF, hybrid) güvenle birleştirir — concat'in 'ilk-gören-kazanır' kayıbını önler.
    Saf fonksiyon (Qdrant/LLM yok) → test edilebilir.
    """
    acc: dict[str, _Hit] = {}
    for results in result_lists:
        for rank, sr in enumerate(results):
            inc = 1.0 / (rank + k)
            existing = acc.get(sr.chunk_id)
            if existing:
                existing.rrf_score += inc
            else:
                acc[sr.chunk_id] = _Hit(sr=sr, rrf_score=inc)
    merged = sorted(acc.values(), key=lambda h: h.rrf_score, reverse=True)
    return [
        SearchResult(
            chunk_id=h.sr.chunk_id, score=float(h.rrf_score), text=h.sr.text,
            source=h.sr.source, source_url=h.sr.source_url, domain=h.sr.domain,
            metadata=h.sr.metadata,
        )
        for h in merged[:top_k]
    ]


async def fan_out_search(
    queries: list[str],
    top_k: int = 10,
    per_query_k: int = 30,
    domain: str | None = None,
    sparse_domain: str | None = None,
    doc_type: str | list[str] | None = None,
) -> list[SearchResult]:
    """Her sorgu için paralel hybrid search → RRF merge → top_k.

    Args:
        queries: Sorgular (ilki genelde orijinal soru).
        top_k: Final sonuç sayısı.
        per_query_k: Her sorgudan çekilecek aday sayısı (RRF için).
        domain: Qdrant payload filter.
        sparse_domain: BGE-M3 sparse embedder seçim hint'i (Qdrant filtresi DEĞİL).
            domain=None (tüm domainlerde ara) iken bile triaj domain'i buradan geçer →
            trafik/icra/vergi alt-sorguları BM25 sparse'ı kaybetmez (denetim 2026-06-04).
    """
    if not queries:
        return []

    # Paralel arama — Qdrant client her sorguda yeniden açılıp kapanır
    tasks = [
        search(question=q, top_k=per_query_k, prefetch_limit=per_query_k,
               domain=domain, sparse_domain=sparse_domain, doc_type=doc_type)
        for q in queries
    ]
    results_per_query = await asyncio.gather(*tasks, return_exceptions=True)

    valid: list[list[SearchResult]] = []
    for q_results in results_per_query:
        if isinstance(q_results, BaseException):
            log.warning("mq_query_failed", error=str(q_results))
            continue
        valid.append(q_results)

    out = rrf_merge(valid, top_k)  # paylaşılan RRF (speculative_search ile tek kaynak)
    log.info("mq_merged", n_queries=len(queries), top_k=len(out))
    return out


async def search_multi_query(
    question: str,
    top_k: int = 10,
    n_queries: int = DEFAULT_N,
    per_query_k: int = 30,
    domain: str | None = None,
    sparse_domain: str | None = None,
    doc_type: str | list[str] | None = None,
) -> list[SearchResult]:
    """Convenience: expand + fan-out tek seferde.

    sparse_domain: domain=None ile aranırken bile BGE-M3 sparse embedder seçimi için
    triaj domain'i geçilir → trafik/icra/vergi MQ alt-sorguları sparse'ı kaybetmez.
    doc_type: query-time law/case filtresi (mevzuat yolu 'law' geçer → case-law gürültüsü dışlanır).
    """
    queries = await expand_queries(question, n=n_queries, domain=domain)
    return await fan_out_search(
        queries, top_k=top_k, per_query_k=per_query_k, domain=domain,
        sparse_domain=sparse_domain, doc_type=doc_type,
    )


# --------------------------------------------------------------------------
#  Helper: JSON-mode parser (Sprint-4 W1) + fallback numbered parser
# --------------------------------------------------------------------------

# JSON fence/prefix temizleme — bazı LLM'ler "```json" ile sarıyor.
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_json_paraphrases(raw: str, max_n: int) -> list[str]:
    """{"paraphrases": ["...", "..."]} JSON nesnesinden listeyi çıkar.

    Tolerant: markdown fence kaldırır; geçersizse boş döner (caller fallback'e
    geçer). Çıktı her zaman list[str], max_n ile kırpılır.
    """
    if not raw:
        return []
    cleaned = _JSON_FENCE_RE.sub("", raw).strip()
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        # JSON modu reddetse de prompt LLM'i serbest bırakmış olabilir.
        # İlk { … } bloğunu çıkar; basit greedy.
        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first == -1 or last <= first:
            return []
        try:
            obj = json.loads(cleaned[first : last + 1])
        except json.JSONDecodeError:
            return []
    items = obj.get("paraphrases", []) if isinstance(obj, dict) else []
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if len(text) >= 5:
            out.append(text)
        if len(out) >= max_n:
            break
    return out


def _parse_numbered(raw: str, max_n: int) -> list[str]:
    """Fallback: '1. ... \\n 2. ...' formatından temiz soru listesi.

    JSON parse başarısız olursa kullanılır. Sprint-4 W1 öncesi default'tı.
    """
    if not raw:
        return []
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    out: list[str] = []
    for line in lines:
        # Numara prefix'i (1., 2), -, *) at
        cleaned = line
        for prefix in ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "-", "*"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break
        if cleaned and len(cleaned) >= 5:
            out.append(cleaned)
        if len(out) >= max_n:
            break
    return out


__all__ = (
    "DEFAULT_N",
    "RRF_K",
    "expand_queries",
    "fan_out_search",
    "reset_cache",
    "rrf_merge",
    "search_multi_query",
)
