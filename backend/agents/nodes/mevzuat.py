"""Mevzuat ajanı — kanun maddelerini retrieve eder.

Strateji:
  - HYDE_ENABLED → hipotetik kanun maddesi üretip onu embed (top score +)
  - MULTI_QUERY_ENABLED → LLM paraphrase fan-out + RRF merge (recall +)
  - İkisi de açıksa sonuçlar tek havuzda birleştirilir
  - İkisi de kapalıysa düz hybrid_search
  - doc_type='law' filter Qdrant'tan post-filter ile
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from agents.config import (
    DOMAIN_CORE_MADDELER,
    DOMAIN_TO_KANUN_KODU,
    HYDE_TIMEOUT_S,
    MEVZUAT_DOMAIN_BOOST,
    MEVZUAT_DOMAIN_FILTER_ENABLED,
    MEVZUAT_RERANK_ENABLED,
    MULTI_QUERY_N,
    SPECULATIVE_DEADLINE_S,
    SPECULATIVE_ENABLED,
    TOP_K_LAW,
)
from agents.state import AgentState, Citation
from core.observability import observe_node
from retrieval.adaptive_router import route_query
from retrieval.hybrid_search import SearchResult, fetch_maddeler, search
from retrieval.hyde import search_with_hyde
from retrieval.multi_query import search_multi_query
from retrieval.query_rewrite import search_with_step_back, should_rewrite
from retrieval.reranker import get_reranker
from retrieval.speculative_search import search_speculative

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

    FAN-IN DAYANIKLILIĞI (denetim 2026-06-04): retrieval beklenmedik bir exception ile
    çökse bile (embedding/Qdrant/reranker) TÜM graph'ı 500'lememeli → boş mevzuat_refs +
    errors döndürür; emsal kolu + verify ayakta kalır (dejenere ama yanıt üretir).
    """
    domain = state.get("domain", "unknown")
    if domain == "unknown":
        return {"mevzuat_refs": []}
    try:
        return await _mevzuat_retrieve(state["question"], domain)
    except Exception as exc:
        log.error("mevzuat_node_degraded", error=str(exc) or type(exc).__name__)
        return {"mevzuat_refs": [], "errors": [f"mevzuat: {type(exc).__name__}"]}


async def _mevzuat_retrieve(question: str, domain: str) -> dict:
    target_k = TOP_K_LAW * 4

    # Adaptive routing: domain + karmaşıklık bazlı HyDE/MQ kararı.
    routing = route_query(question, domain)
    log.info(
        "mevzuat_routing",
        strategy=routing.strategy,
        complexity=routing.complexity,
        domain=domain,
    )

    # Spekülatif arama: hybrid HEMEN başlar, HyDE/MQ paralel arka planda.
    # Kullanıcı max SPECULATIVE_DEADLINE_S ek bekler (~2s), sonra hybrid fallback.
    # SPECULATIVE_ENABLED=0 ise eski gather davranışına dön (test/debug için).
    results: list[SearchResult]
    # doc_type="law" (denetim 2026-06-04, ÖLÇÜLDÜ +15.8pp madde_recall@5): query-time law
    # filtresi → case-law (anayasa, corpus %64) gürültüsü top-K'yı kirletip mevzuat maddelerini
    # dışarı itmez. Eski post-filter havuzdan çıkmış maddeyi kurtaramıyordu. (emsal_node ayrı kol.)
    if SPECULATIVE_ENABLED and (routing.use_hyde or routing.use_mq):
        results, retrieval_mode = await search_speculative(
            question=question,
            routing=routing,
            top_k=target_k,
            target_k=target_k,
            multi_query_n=MULTI_QUERY_N,
            hyde_timeout_s=HYDE_TIMEOUT_S,
            deadline_s=SPECULATIVE_DEADLINE_S,
            doc_type="law",
        )
    elif routing.use_hyde or routing.use_mq:
        # Eski davranış: gather ile tam HyDE/MQ bekleme
        retrieval_modes: list[str] = []
        results = []
        timeout_total = HYDE_TIMEOUT_S + 25.0
        _tasks: dict[str, Any] = {}
        if routing.use_hyde:
            _tasks["hyde"] = search_with_hyde(question, top_k=target_k, domain=domain,
                                              qdrant_domain=None, sparse_domain=domain, doc_type="law")
        if routing.use_mq:
            _tasks["mq"] = search_multi_query(question, top_k=target_k, n_queries=MULTI_QUERY_N,
                                              domain=None, sparse_domain=domain, doc_type="law")
        _keys = list(_tasks.keys())
        _coros = [asyncio.wait_for(c, timeout=timeout_total) for c in _tasks.values()]
        _done = await asyncio.gather(*_coros, return_exceptions=True)
        for _key, _result in zip(_keys, _done):
            if isinstance(_result, BaseException):
                if isinstance(_result, _RETRIEVAL_FALLBACK_EXCEPTIONS):
                    log.warning(f"{_key}_timeout_fallback", error=str(_result) or type(_result).__name__)
                    retrieval_modes.append(f"{_key}_failed")
                else:
                    raise _result
            else:
                results = _merge_dedup(_result, results)  # type: ignore[arg-type]
                retrieval_modes.append(_key)
        if not results:
            results = await search(question=question, top_k=target_k, sparse_domain=domain, doc_type="law")
            retrieval_modes.append("hybrid")
        retrieval_mode = "+".join(retrieval_modes)
    else:
        results = await search(question=question, top_k=target_k, sparse_domain=domain, doc_type="law")
        retrieval_mode = "hybrid"

    # Step-back query rewrite (opt-in, 1.1): konuşma-dili sorguyu resmî hukuki terimlere
    # çevirip AYRI arar + RRF ile havuza katar VE rewrite'ı rerank sorgusu yapar →
    # cross-encoder ranking-reversal'ı (konuşma-dili → yanlış madde) hedefler. rewrite ""
    # ise (LLM yok/başarısız/no-op) baseline birebir korunur. Default OFF (should_rewrite False).
    rerank_query = question
    if should_rewrite(question, domain):
        try:
            sb_results, rewrite = await search_with_step_back(
                question, top_k=target_k, per_query_k=target_k,
                sparse_domain=domain, doc_type="law",
            )
            if rewrite:
                results = _merge_dedup(sb_results, results)
                rerank_query = rewrite
                retrieval_mode = f"{retrieval_mode}+stepback"
        except _RETRIEVAL_FALLBACK_EXCEPTIONS as exc:
            log.warning("step_back_failed", error=str(exc) or type(exc).__name__)

    laws = await _rank_and_build_laws(
        question, domain, results, retrieval_mode, rerank_query=rerank_query,
    )
    return {"mevzuat_refs": laws}


async def _rank_and_build_laws(
    question: str, domain: str, results: list[SearchResult], retrieval_mode: str,
    rerank_query: str | None = None,
) -> list[Citation]:
    """Retrieve sonrası law adaylarını sırala + çapa garantisi + Citation üret.

    mevzuat_node'dan ayrıldı (C901 — node 17>15 dal). Sıra:
      1. domain-scoped takviye arama (vatandaş-dili köprüsü)
      2. domain boost
      3. law adayları ayıkla + çapa maddeleri ekle
      4. cross-encoder rerank (+ çapaları geri-merge)
      5. domain-öncelikli tier sort
      6. çapa-garantili final top-K → Citation
    """
    # 1. Domain-scoped takviye retrieval. Vatandaş dili ("buzdolabı bozuldu")
    # genel aramada doğru kanunu (TKHK m.11 "ayıplı mal") top-K'ya getiremiyor —
    # kelime örtüşmesi yok, TTK gibi kalabalık kanunlar baskın. O domain'in kanun
    # setine FİLTRELİ ek arama yapıp havuza katıyoruz; ilgili kanunlar GARANTİ aday.
    if MEVZUAT_DOMAIN_FILTER_ENABLED and domain in DOMAIN_TO_KANUN_KODU:
        try:
            scoped = await search(
                question=question,
                top_k=TOP_K_LAW * 2,
                kanun_kodu=list(DOMAIN_TO_KANUN_KODU[domain]),
            )
            results = _merge_dedup(scoped, results)
        except _RETRIEVAL_FALLBACK_EXCEPTIONS as exc:
            log.warning("domain_scoped_retrieval_failed",
                        error=str(exc) or type(exc).__name__)

    # 2. Pre-domain boost — domain'e uyan `kanun_kodu` skoru +MEVZUAT_DOMAIN_BOOST.
    n_boosted = 0
    if MEVZUAT_DOMAIN_FILTER_ENABLED and domain in DOMAIN_TO_KANUN_KODU:
        results, n_boosted = _boost_by_domain(results, domain)

    # 3. law adaylarını ayıkla (doc_type=='law' VEYA source=='mevzuat')
    law_cands = [
        r for r in results
        if r.metadata.get("doc_type") == "law" or r.source == "mevzuat"
    ]

    # Çapa-maddeler — domain'in kilit maddelerini (örn. İş Hukuku ihbar İK m.17,
    # kıdem EIK m.14) aday havuzuna GARANTİ et. Konuşma-dili sorguda noise-floor
    # cross-encoder bunları top-K'dan düşürüyordu; filtreyle çekip merge ediyoruz.
    anchors: list[SearchResult] = []
    if MEVZUAT_DOMAIN_FILTER_ENABLED and domain in DOMAIN_CORE_MADDELER:
        try:
            anchors = await fetch_maddeler(list(DOMAIN_CORE_MADDELER[domain]))
        except _RETRIEVAL_FALLBACK_EXCEPTIONS as exc:
            log.warning("anchor_fetch_failed", error=str(exc) or type(exc).__name__)
    anchor_ids = {a.chunk_id for a in anchors}
    if anchors:
        law_cands = _merge_dedup(law_cands, anchors)

    # 4. Cross-encoder rerank — RRF+boost heuristic'i kalabalık kanunları (TTK 405
    # chunk) öne koyabiliyor; cross-encoder gerçek soru-belge alakasıyla TKHK m.11
    # gibi ilgili maddeleri başa çıkarır. Reranker yoksa/çökerse boosted sıra korunur.
    reranked = False
    if MEVZUAT_RERANK_ENABLED and law_cands:
        try:
            rr = await asyncio.to_thread(
                get_reranker().rerank, rerank_query or question, law_cands, TOP_K_LAW * 3,
            )
            if rr:
                law_cands = rr
                reranked = True
        except Exception as exc:
            log.warning("mevzuat_rerank_failed", error=str(exc) or type(exc).__name__)

    # rerank, çapaları noise-floor skorla kesmiş olabilir → geri ekle (recall garanti)
    if anchors:
        law_cands = _merge_dedup(law_cands, anchors)

    # 5. Domain-öncelikli tier sort — cross-encoder alakayı verir AMA hukuki bağlamı
    # (tüketici vs deniz ticareti) ayırt edemez. Triaj domain'inin BİRİNCİL kanunu
    # (tuketici→TKHK) tier-0'a alınır; cross-encoder sırası tier İÇİNDE korunur.
    n_primary = 0
    if MEVZUAT_DOMAIN_FILTER_ENABLED and domain in DOMAIN_TO_KANUN_KODU:
        law_cands, n_primary = _domain_priority_rerank(law_cands, domain)

    # 6. Final top-K: çapa maddeleri GARANTİ et, kalanı sıralı doldur.
    final_cands = _ensure_core_in_topk(law_cands, anchor_ids, TOP_K_LAW)
    laws = [
        Citation(
            source_id=r.chunk_id,
            doc_type="law",
            title=_format_law_title(r),
            snippet=r.text[:500],
            url=r.source_url,
            score=r.score,
        )
        for r in final_cands
    ]

    log.info(
        "mevzuat_done",
        domain=domain, n=len(laws), mode=retrieval_mode,
        boosted=n_boosted, reranked=reranked, primary=n_primary,
        anchors=len(anchor_ids),
    )
    return laws


def _merge_dedup(
    primary: list[SearchResult], secondary: list[SearchResult],
) -> list[SearchResult]:
    """İki sonuç listesini chunk_id'ye göre tekilleştirerek birleştir.

    `primary` öncelikli: aynı chunk_id iki listede de varsa primary'deki
    (domain-scoped, daha güvenilir skor) korunur. Sıralama sonradan
    `_boost_by_domain` skor-desc sort'u ile belirlenir.
    """
    seen: dict[str, SearchResult] = {}
    for r in [*primary, *secondary]:
        if r.chunk_id not in seen:
            seen[r.chunk_id] = r
    return list(seen.values())


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


def _domain_priority_rerank(
    cands: list, domain: str,
) -> tuple[list, int]:
    """Cross-encoder sırasını domain-önceliğiyle birleştir (stable tier sort).

    Cross-encoder relevance'ı verir ama hukuki bağlamı ayırt edemez. Triaj
    domain'inin BİRİNCİL kanunu (DOMAIN_TO_KANUN_KODU tuple'ının ilk elemanı,
    örn. tuketici→TKHK) tier-0'a alınır; aynı domain'in diğer kanunları tier-1;
    domain dışı tier-2. `sorted` stable olduğundan tier İÇİNDE mevcut
    (cross-encoder) sıra korunur — yani TKHK maddeleri kendi alaka sırasında
    kalır, sadece TTK/TBK gürültüsünün üstüne çıkar.

    Returns:
        (re-sıralı liste, birincil-kanun chunk sayısı).
    """
    kodlar = DOMAIN_TO_KANUN_KODU.get(domain, ())
    if not kodlar:
        return cands, 0
    primary = kodlar[0]
    domain_set = set(kodlar)

    def _tier(c) -> int:
        kod = str(c.metadata.get("kanun_kodu") or "")
        if kod == primary:
            return 0
        if kod in domain_set:
            return 1
        return 2

    ordered = sorted(cands, key=_tier)  # stable → tier içinde cross-encoder sırası
    n_primary = sum(
        1 for c in cands if str(c.metadata.get("kanun_kodu") or "") == primary
    )
    return ordered, n_primary


def _ensure_core_in_topk(
    ranked: list, anchor_ids: set[str], top_k: int,
) -> list:
    """Final top_k'da çapa maddelerini GARANTİ et; kalanı ranked sırasıyla doldur.

    `_domain_priority_rerank` çıktısı zaten domain-öncelikli sıralı. Çapalar
    (anchor_ids) genelde birincil kanunda olduğundan tier-0'a düşer ve doğal
    olarak başa gelir; ama corpus'ta birden çok madde olunca top_k taşabilir.
    Bu fonksiyon çapaları önce yerleştirip (ranked sırasını koruyarak), kalan
    slotları yine ranked sırasıyla doldurur — yani hiçbir çapa top_k dışında
    kalmaz, ama genel sıralama bozulmaz.
    """
    if not anchor_ids:
        return ranked[:top_k]
    pos = {r.chunk_id: i for i, r in enumerate(ranked)}
    chosen: list = []
    seen: set[str] = set()
    for r in ranked:  # 1. çapalar önce (ranked sırasında)
        if r.chunk_id in anchor_ids and r.chunk_id not in seen:
            chosen.append(r)
            seen.add(r.chunk_id)
    for r in ranked:  # 2. kalan slotları doldur
        if len(chosen) >= top_k:
            break
        if r.chunk_id not in seen:
            chosen.append(r)
            seen.add(r.chunk_id)
    chosen.sort(key=lambda r: pos[r.chunk_id])  # 3. ranked sırasını geri getir
    return chosen[:top_k]


def _format_law_title(r) -> str:
    """'İcra ve İflas Kanunu (IIK) Madde 62' tarzı başlık — kanun_adi varsa açık ad +
    kısaltma; yoksa kompakt 'IIK Madde 62'. Açık ad LLM'in 'IIK'yı 'İş Kanunu' diye yanlış
    açmasını önler (2026-06-04 icra ölçümü); kanun_adi payload'da zaten mevcut."""
    kod = r.metadata.get("kanun_kodu", "")
    madde = r.metadata.get("madde_no", "")
    kanun_adi = (r.metadata.get("kanun_adi") or "").strip()
    if kod and madde:
        if kanun_adi:
            return f"{kanun_adi} ({kod}) Madde {madde}"
        return f"{kod} Madde {madde}"
    return r.metadata.get("title") or r.source or r.chunk_id
