"""Mevzuat ajanı — kanun maddelerini retrieve eder.

Strateji:
  - MULTI_QUERY_ENABLED → LLM paraphrase fan-out + RRF merge (recall +)
  - HYDE_ENABLED → hipotetik kanun maddesi üretip onu embed (top score +)
  - İkisi de kapalıysa düz hybrid_search
  - doc_type='law' filter Qdrant'tan post-filter ile
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

from agents.config import (
    DOMAIN_TO_KANUN_KODU,
    HYDE_ENABLED,
    HYDE_TIMEOUT_S,
    MEVZUAT_DOMAIN_BOOST,
    MEVZUAT_DOMAIN_FILTER_ENABLED,
    MULTI_QUERY_ENABLED,
    MULTI_QUERY_N,
    TOP_K_LAW,
)
from agents.state import AgentState, Citation
from core.observability import observe_node
from retrieval.hybrid_search import SearchResult, search
from retrieval.hyde import search_with_hyde
from retrieval.multi_query import search_multi_query

log = structlog.get_logger()

# Sprint-4 W1: silent `except Exception` antipattern'i daraltıldı.
# Yutulan exception tipleri — geri kalan her şey (TypeError, ValueError vb.)
# propagate olur ki gerçek bug'lar görünür kalsın.
# - asyncio.TimeoutError: wait_for timeout
# - httpx.HTTPError: llama-server / Qdrant network hatası
# - ConnectionError: Qdrant erişilemez
# CancelledError ASLA yutulmaz (asyncio cooperative cancel propagate olmalı).
_RETRIEVAL_FALLBACK_EXCEPTIONS = (asyncio.TimeoutError, httpx.HTTPError, ConnectionError)


@observe_node(name="mevzuat")
async def mevzuat_node(state: AgentState) -> dict:
    """Mevzuat retrieval — kanun maddelerini getir.

    NOT: Mevzuat seed'lerinde `domain` field yok (sonra fix), bu yüzden
    Qdrant'a domain filter'ı geçirmiyoruz. Post-filter doc_type=='law'
    veya source=='mevzuat' ile law'ları ayırıyoruz.

    HyDE+multi-query stratejisi: vatandaş dilini kanun jargonuna çevirmek
    için HyDE; lexical varyasyon için multi-query. E7 vergi (top=0.66) ve
    E8 tapu (top=0.62) gibi düşük skorlu sorgulara yardım eder.
    """
    question = state["question"]
    domain = state.get("domain", "unknown")
    if domain == "unknown":
        return {"mevzuat_refs": []}

    target_k = TOP_K_LAW * 4
    # HYDE_TIMEOUT_S sadece LLM hipotetik üretimi içindi — toplam search süresine
    # Qdrant + embedder de eklenince +6s buffer makul (v11 ölçümünde 14B Q4 ile
    # 200-token üretim ortalama 15-20s sürüyor; eski 2s+8 buffer çok dar idi).
    timeout_total = HYDE_TIMEOUT_S + 25.0
    if HYDE_ENABLED:
        # HyDE: dense kanal LLM-üretimi hipotetik kanun maddesini embed eder
        try:
            results = await asyncio.wait_for(
                search_with_hyde(
                    question, top_k=target_k, domain=domain, qdrant_domain=None,
                ),
                timeout=timeout_total,
            )
            retrieval_mode = "hyde"
        except _RETRIEVAL_FALLBACK_EXCEPTIONS as exc:
            # Fallback: plain hybrid. asyncio TimeoutError str() boş gelir, type ekle.
            log.warning("hyde_timeout_fallback",
                        error=str(exc) or type(exc).__name__,
                        exc_type=type(exc).__name__,
                        timeout_s=timeout_total)
            results = await search(question=question, top_k=target_k, domain=None)
            retrieval_mode = "hybrid_after_hyde_fail"
    elif MULTI_QUERY_ENABLED:
        # Multi-query: N paraphrase fan-out + RRF merge (lexical recall)
        try:
            results = await asyncio.wait_for(
                search_multi_query(
                    question, top_k=target_k, n_queries=MULTI_QUERY_N, domain=None,
                ),
                timeout=timeout_total,
            )
            retrieval_mode = "multi_query"
        except _RETRIEVAL_FALLBACK_EXCEPTIONS as exc:
            log.warning("multi_query_timeout_fallback",
                        error=str(exc) or type(exc).__name__,
                        exc_type=type(exc).__name__,
                        timeout_s=timeout_total)
            results = await search(question=question, top_k=target_k, domain=None)
            retrieval_mode = "hybrid_after_mq_fail"
    else:
        results = await search(question=question, top_k=target_k, domain=None)
        retrieval_mode = "hybrid"

    # Sprint-4 W1: Pre-domain boost — triaj'ın belirlediği domain'e uyan
    # `kanun_kodu` payload'larını skoru +MEVZUAT_DOMAIN_BOOST ile re-rank et.
    # Mevzuat seed'lerinde `domain` field yok ama `kanun_kodu` var; boost
    # post-retrieve uygulanır → re-seed gerekmez.
    n_boosted = 0
    if MEVZUAT_DOMAIN_FILTER_ENABLED and domain in DOMAIN_TO_KANUN_KODU:
        results, n_boosted = _boost_by_domain(results, domain)

    laws: list[Citation] = []
    for r in results:
        # law kriteri: doc_type=='law' VEYA source=='mevzuat'
        is_law = r.metadata.get("doc_type") == "law" or r.source == "mevzuat"
        if not is_law:
            continue
        laws.append(
            Citation(
                source_id=r.chunk_id,
                doc_type="law",
                title=_format_law_title(r),
                snippet=r.text[:500],
                url=r.source_url,
                score=r.score,
            )
        )
        if len(laws) >= TOP_K_LAW:
            break

    log.info(
        "mevzuat_done",
        domain=domain, n=len(laws), mode=retrieval_mode, boosted=n_boosted,
    )
    return {"mevzuat_refs": laws}


def _boost_by_domain(
    results: list[SearchResult], domain: str,
) -> tuple[list[SearchResult], int]:
    """Domain'e uyan `kanun_kodu` chunk'larının skorunu boost ile yeniden sırala.

    Args:
        results: hybrid_search'den gelen aday liste (skor sıralı).
        domain: triaj domain'i (tuketici, isHukuku, ...).

    Returns:
        (re-ranked list, boost uygulanan chunk sayısı). Boost asla skoru
        düşürmez; yalnız uyumlu olanların skoruna sabit `MEVZUAT_DOMAIN_BOOST`
        eklenir, sonra desc-sort. Uyumsuz veya kanun_kodu olmayan chunk'lar
        orijinal skor ile kalır — listede yine dönerler, sadece geride.
    """
    target_kodlar = set(DOMAIN_TO_KANUN_KODU.get(domain, ()))
    if not target_kodlar:
        return results, 0

    boosted: list[SearchResult] = []
    n_match = 0
    for r in results:
        kod = str(r.metadata.get("kanun_kodu") or "")
        if kod and kod in target_kodlar:
            n_match += 1
            boosted.append(
                SearchResult(
                    chunk_id=r.chunk_id,
                    score=r.score + MEVZUAT_DOMAIN_BOOST,
                    text=r.text,
                    source=r.source,
                    source_url=r.source_url,
                    domain=r.domain,
                    metadata=r.metadata,
                )
            )
        else:
            boosted.append(r)

    boosted.sort(key=lambda x: x.score, reverse=True)
    return boosted, n_match


def _format_law_title(r) -> str:
    """'TKHK Madde 11' tarzı kompakt başlık."""
    kod = r.metadata.get("kanun_kodu", "")
    madde = r.metadata.get("madde_no", "")
    if kod and madde:
        return f"{kod} Madde {madde}"
    return r.metadata.get("title") or r.source or r.chunk_id
