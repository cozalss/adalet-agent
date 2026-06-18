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
import os
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
from core.text import tr_lower
from retrieval.adaptive_router import route_query
from retrieval.hybrid_search import (
    SearchResult,
    colbert_rerank_candidates,
    colbert_rerank_enabled,
    fetch_maddeler,
    search,
)
from retrieval.hyde import search_with_hyde
from retrieval.mevzuat_urls import normalize_mevzuat_url
from retrieval.multi_query import fan_out_search, search_multi_query
from retrieval.query_rewrite import (
    decontextualize_for_retrieval,
    search_with_step_back,
    should_rewrite,
)
from retrieval.reranker import get_reranker
from retrieval.speculative_search import search_speculative
from retrieval.typo_tolerance import typo_retrieval_variants

log = structlog.get_logger()

# Sprint-4 W1: silent `except Exception` antipattern'i daraltıldı.
# Yutulan exception tipleri — geri kalan her şey (TypeError, ValueError vb.)
# propagate olur ki gerçek bug'lar görünür kalsın.
# - asyncio.TimeoutError: wait_for timeout
# - httpx.HTTPError: llama-server / Qdrant network hatası
# - ConnectionError: Qdrant erişilemez
# CancelledError ASLA yutulmaz (asyncio cooperative cancel propagate olmalı).
_RETRIEVAL_FALLBACK_EXCEPTIONS = (asyncio.TimeoutError, httpx.HTTPError, ConnectionError)

# Mevzuat aramasının doc_type kapsamı (P4, 2026-06-10): law + regulation. 128 yönetmelik
# chunk'ı (Mesafeli/Garanti/THH/SSH — vatandaş sorularının tam hedefi: "cayma 14 gün")
# salt-law filtrede HİÇBİR retrieval yoluna girmiyordu (ölü ağırlık). Regulation chunk'ları
# source='mevzuat' olduğundan ranking zincirinin law-aday filtresinden zaten geçer;
# tek engel query-time filtreydi. eval_run --mode node da bu sabiti kullanır (parite).
MEVZUAT_DOC_TYPES: list[str] = ["law", "regulation"]


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
        # Multi-turn: takip sorusunu ("peki 1 yıldan az çalıştıysam") chat_history ile
        # bağımsız hukuki sorguya çevir → retrieval çıpa kazanır. Opt-in + graceful
        # (kapalı/başarısız → orijinal question, baseline). Orijinal soru draft'a gider.
        retrieval_q = await decontextualize_for_retrieval(
            state["question"], state.get("chat_history") or [], domain
        )
        return await _mevzuat_retrieve(retrieval_q, domain)
    except Exception as exc:
        log.error("mevzuat_node_degraded", error=str(exc) or type(exc).__name__)
        return {"mevzuat_refs": [], "errors": [f"mevzuat: {type(exc).__name__}"]}


def mevzuat_pool_k() -> int:
    """Başlangıç retrieval havuzu boyutu — TOP_K_LAW × MEVZUAT_POOL_MULT (default 4 = 32).

    icra teşhisi (2026-06-11): IIK-148/177 gibi niş alt-konu maddeleri top-32'ye
    giremiyor (chunk'lar gerçek/konu-doğru, doğrulandı) → havuz-tavanı denemesi
    için knob. eval_run --mode node aynı helper'ı kullanır (parite).
    """
    try:
        mult = int(os.getenv("MEVZUAT_POOL_MULT", "4"))
    except ValueError:
        mult = 4
    return TOP_K_LAW * max(mult, 1)


async def _mevzuat_retrieve(question: str, domain: str) -> dict:
    target_k = mevzuat_pool_k()

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
    # doc_type=MEVZUAT_DOC_TYPES (denetim 2026-06-04, ÖLÇÜLDÜ +15.8pp madde_recall@5): query-time
    # filtre → case-law (anayasa, corpus %64) gürültüsü top-K'yı kirletip mevzuat maddelerini
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
            doc_type=MEVZUAT_DOC_TYPES,
        )
    elif routing.use_hyde or routing.use_mq:
        # Eski davranış: gather ile tam HyDE/MQ bekleme
        retrieval_modes: list[str] = []
        results = []
        timeout_total = HYDE_TIMEOUT_S + 25.0
        _tasks: dict[str, Any] = {}
        if routing.use_hyde:
            _tasks["hyde"] = search_with_hyde(question, top_k=target_k, domain=domain,
                                              qdrant_domain=None, sparse_domain=domain, doc_type=MEVZUAT_DOC_TYPES)
        if routing.use_mq:
            _tasks["mq"] = search_multi_query(question, top_k=target_k, n_queries=MULTI_QUERY_N,
                                              domain=None, sparse_domain=domain, doc_type=MEVZUAT_DOC_TYPES)
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
            results = await search(question=question, top_k=target_k, sparse_domain=domain, doc_type=MEVZUAT_DOC_TYPES)
            retrieval_modes.append("hybrid")
        retrieval_mode = "+".join(retrieval_modes)
    else:
        results = await search(question=question, top_k=target_k, sparse_domain=domain, doc_type=MEVZUAT_DOC_TYPES)
        retrieval_mode = "hybrid"

    results, retrieval_mode = await apply_typo_variants(
        question, domain, results, retrieval_mode,
    )

    results, rerank_query, retrieval_mode = await apply_step_back(
        question, domain, results, retrieval_mode,
    )

    laws = await _rank_and_build_laws(
        question, domain, results, retrieval_mode, rerank_query=rerank_query,
    )
    return {"mevzuat_refs": laws}


async def apply_typo_variants(
    question: str, domain: str, results: list[SearchResult], retrieval_mode: str,
) -> tuple[list[SearchResult], str]:
    """Add a deterministic typo-corrected retrieval branch when needed.

    Multi-query already includes typo variants, so this helper mainly covers
    hybrid/HyDE/speculative-fallback paths. It is a no-op for clean queries.
    """
    if "mq" in retrieval_mode and "failed" not in retrieval_mode and "fallback" not in retrieval_mode:
        return results, retrieval_mode
    variants = typo_retrieval_variants(question, max_variants=1)
    if not variants:
        return results, retrieval_mode
    try:
        typo_results = await fan_out_search(
            variants,
            top_k=mevzuat_pool_k(),
            per_query_k=mevzuat_pool_k(),
            domain=None,
            sparse_domain=domain,
            doc_type=MEVZUAT_DOC_TYPES,
        )
        if typo_results:
            return _merge_dedup(results, typo_results), f"{retrieval_mode}+typo"
    except _RETRIEVAL_FALLBACK_EXCEPTIONS as exc:
        log.warning("typo_variant_retrieval_failed", error=str(exc) or type(exc).__name__)
    return results, retrieval_mode


async def apply_step_back(
    question: str, domain: str, results: list[SearchResult], retrieval_mode: str,
) -> tuple[list[SearchResult], str, str]:
    """Step-back query rewrite (opt-in, 1.1) — (results, rerank_query, mode) döndürür.

    Konuşma-dili sorguyu resmî hukuki terimlere çevirip AYRI arar + RRF ile havuza
    katar VE rewrite'ı rerank sorgusu yapar → cross-encoder ranking-reversal'ı
    (konuşma-dili → yanlış madde) hedefler. rewrite "" ise (LLM yok/başarısız/no-op)
    baseline birebir korunur. Default OFF (should_rewrite False; QUERY_REWRITE_ENABLED=1).
    _mevzuat_retrieve'den ayrıldı (P7 2026-06-10): eval_run --mode node da bu adımı
    production-pariteli koşar (önceden eval node-yolu step-back'i hiç içermiyordu →
    flag'in etkisi ölçülemiyordu).
    """
    rerank_query = question
    if should_rewrite(question, domain):
        try:
            sb_results, rewrite = await search_with_step_back(
                question, top_k=mevzuat_pool_k(), per_query_k=mevzuat_pool_k(),
                sparse_domain=domain, doc_type=MEVZUAT_DOC_TYPES,
            )
            if rewrite:
                results = _merge_dedup(sb_results, results)
                rerank_query = rewrite
                retrieval_mode = f"{retrieval_mode}+stepback"
        except _RETRIEVAL_FALLBACK_EXCEPTIONS as exc:
            log.warning("step_back_failed", error=str(exc) or type(exc).__name__)
    return results, rerank_query, retrieval_mode


async def _rank_and_build_laws(
    question: str, domain: str, results: list[SearchResult], retrieval_mode: str,
    rerank_query: str | None = None,
) -> list[Citation]:
    """Retrieve sonrası law adaylarını sırala + çapa garantisi + Citation üret."""
    final_cands = await rank_law_candidates(
        question, domain, results, retrieval_mode, rerank_query=rerank_query,
    )
    return [
        Citation(
            source_id=r.chunk_id,
            doc_type="law",
            title=_format_law_title(r),
            snippet=r.text[:500],
            url=normalize_mevzuat_url(r.source_url, r.metadata),
            score=r.score,
        )
        for r in final_cands
    ]


async def rank_law_candidates(
    question: str, domain: str, results: list[SearchResult], retrieval_mode: str,
    rerank_query: str | None = None,
) -> list[SearchResult]:
    """Production madde-ranking zinciri — SearchResult döndürür (Citation'sız).

    mevzuat_node'dan ayrıldı (C901 — node 17>15 dal); eval_run `--mode node` da
    bu zinciri ÇIPLAK search_with_rerank yerine doğrudan ölçer (eval %42.8 vs
    production %84.4 uçurumunun kapanması, öncelik #1 2026-06-10). Sıra:
      1. domain-scoped takviye arama (vatandaş-dili köprüsü)
      2. domain boost
      3. law adayları ayıkla + çapa maddeleri ekle
      4. cross-encoder rerank (+ çapaları geri-merge)
      5. domain-öncelikli tier sort
      6. çapa-garantili final top-K
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

    # 3. mevzuat adaylarını ayıkla (doc_type ∈ {law, regulation} VEYA source=='mevzuat')
    law_cands = [
        r for r in results
        if r.metadata.get("doc_type") in MEVZUAT_DOC_TYPES or r.source == "mevzuat"
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

    # rerank-öncesi yönetmelik adaylarını yakala (aşağıdaki geri-merge için).
    reg_cands = [r for r in law_cands if r.metadata.get("doc_type") == "regulation"]

    # 4. Cross-encoder rerank — RRF+boost heuristic'i kalabalık kanunları (TTK 405
    # chunk) öne koyabiliyor; cross-encoder gerçek soru-belge alakasıyla TKHK m.11
    # gibi ilgili maddeleri başa çıkarır. Reranker yoksa/çökerse boosted sıra korunur.
    reranked = False
    if MEVZUAT_RERANK_ENABLED and law_cands:
        try:
            # RERANK_PROVIDER=bgem3 → BGE-M3 ColBERT multi-vector (ince madde-ayrımı, +5.2pp
            # eval); aksi → cross-encoder. Bu dal colbert'i PRODUCTION madde-ranking'e taşır
            # (eval search_with_rerank'i ölçüyordu; node ayrı path'tı). Default local (CE).
            if colbert_rerank_enabled():
                rr = await colbert_rerank_candidates(rerank_query or question, law_cands, TOP_K_LAW * 3)
            else:
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

    # Yönetmelik adayları stored-ColBERT yan koleksiyonunda YOK (law-only seed) →
    # bgem3 rerank'te kuyruğa düşüp top-K*3 kesiminde elenebilirler; çapa deseniyle
    # geri-merge et — gerçek sıralama kararını tier-sort + final top-K versin (P4).
    if reg_cands:
        law_cands = _merge_dedup(law_cands, reg_cands)

    # 5. Domain-öncelikli tier sort — cross-encoder alakayı verir AMA hukuki bağlamı
    # (tüketici vs deniz ticareti) ayırt edemez. Triaj domain'inin BİRİNCİL kanunu
    # (tuketici→TKHK) tier-0'a alınır; cross-encoder sırası tier İÇİNDE korunur.
    n_primary = 0
    if MEVZUAT_DOMAIN_FILTER_ENABLED and domain in DOMAIN_TO_KANUN_KODU:
        law_cands, n_primary = _domain_priority_rerank(law_cands, domain)

    # 5.4-5.5 Garanti seti: (tavanlı) çapalar + 1 yönetmelik slotu — detay helper'da.
    anchor_ids = _final_guaranteed_ids(law_cands, anchor_ids, question=question, domain=domain)

    # 6. Final top-K: çapa maddeleri GARANTİ et, kalanı sıralı doldur.
    final_cands = _ensure_core_in_topk(law_cands, anchor_ids, TOP_K_LAW)

    log.info(
        "mevzuat_done",
        domain=domain, n=len(final_cands), mode=retrieval_mode,
        boosted=n_boosted, reranked=reranked, primary=n_primary,
        anchors=len(anchor_ids),
    )
    return final_cands


def _anchor_slot_cap() -> int:
    """Final top-K'da GARANTİLİ çapa sayısı tavanı (0 = sınırsız).

    DEFAULT 5 — ÖLÇÜLDÜ (2026-06-10, v3 dev sweep 4/5/6 + tek-atış holdout doğrulama):
    dev madde@8 65.9→69.2 (+3.3pp, @5 -0.6 kabul), holdout 51.0→54.1 (+3.1pp, @5 düz,
    hiçbir domain gerilemedi; icra 33→42, tapu 30→40). Kök neden: icra'da 6 çapa
    top-8'in 6 slotunu her sorguda işgal ediyordu → havuz #1'deki sorgu-spesifik
    madde bile final'e giremiyordu. cap=4 tapu'yu üzüyordu (-10 dev), cap=6 etkisiz.
    """
    try:
        return int(os.getenv("MEVZUAT_ANCHOR_SLOT_CAP", "5"))
    except ValueError:
        return 5


# Sorgu-spesifik çapa koruması: sorgu BELİRLİ bir maddeyi işaret ediyorsa o çapa,
# anchor-cap kesiminde elenmemeli. draft._PROMPT_REF_HINTS'in retrieval-eşi — ama orası
# yalnız madde refs'e ULAŞTIYSA çalışır; bu kapı maddeyi refs'e ULAŞTIRIR.
# Örn: kira "fahiş zam / yasal sınır / TÜFE" → TBK 344 (artış tavanı). m.344 cross-encoder'da
# "yenilenen kira dönemi" başlığıyla vatandaş-diline zayıf eşleşir → cap=5'te 6-7. sıraya düşüp
# eleniyordu → cevap m.343/345 ile dolup ASIL sınırı (m.344) atlıyordu (ölçülen prod hatası).
_QUERY_PRIORITY_ANCHORS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("kira",
     ("zam", "artış", "artis", "yüzde", "yuzde", "tüfe", "tufe", "fahiş", "fahis",
      "yasal sınır", "yasal sinir", "oran", "üfe", "ufe"),
     "m-TBK-344"),
)


def _query_priority_anchor_ids(question: str, domain: str) -> set[str]:
    """Sorgunun spesifik olarak işaret ettiği çapa chunk_id'leri (cap'ten muaf)."""
    low = tr_lower(question or "")
    out: set[str] = set()
    for dom, markers, chunk_id in _QUERY_PRIORITY_ANCHORS:
        if domain == dom and any(m in low for m in markers):
            out.add(chunk_id)
    return out


def _final_guaranteed_ids(
    law_cands: list, anchor_ids: set[str], question: str = "", domain: str = "",
) -> set[str]:
    """Final top-K'da garanti edilecek chunk_id seti.

    (a) Çapa-tavanı (2026-06-10 icra teşhisi): icra'da 6 çapa top-8'in 6 slotunu HER
    sorguda işgal ediyordu → sorgu-spesifik madde (IIK 32 havuz #4'te!) final'e
    giremiyordu. Tavan: tier-sort sonrası EN İYİ sıradaki N çapa garantili kalır,
    gerisi normal aday gibi yarışır (havuzdan düşmez, yalnız garanti kaybeder).
    Default 0 = sınırsız; MEVZUAT_ANCHOR_SLOT_CAP ile aç.
    (a2) Sorgu-spesifik istisna: sorgu belirli bir çapayı işaret ediyorsa (kira artış
    → TBK 344) o çapa cap dışında kalsa bile garantilenir → ASIL madde cevaba girer.
    (b) Yönetmelik slot-garantisi (P4): tier-0 birincil kanun top-K'yı tek başına
    doldurur → en iyi sıradaki yönetmelik adayı 1 slot garanti alır (yonetmelik-bench
    kanun@8 %46→%100, v2 law-gold nötr ölçüldü).
    """
    cap = _anchor_slot_cap()
    if cap > 0 and len(anchor_ids) > cap:
        ranked_anchor_ids = [r.chunk_id for r in law_cands if r.chunk_id in anchor_ids]
        kept = set(ranked_anchor_ids[:cap])
        # Sorgu-spesifik çapa cap dışında kalmasın (havuzda varsa geri-garantile).
        for pid in _query_priority_anchor_ids(question, domain):
            if pid in anchor_ids:
                kept.add(pid)
        anchor_ids = kept
    best_reg = next(
        (r for r in law_cands if r.metadata.get("doc_type") == "regulation"), None,
    )
    if best_reg is not None:
        anchor_ids = anchor_ids | {best_reg.chunk_id}
    return anchor_ids


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
    madde = str(r.metadata.get("madde_no", "") or "")
    kanun_adi = (r.metadata.get("kanun_adi") or "").strip()
    # P8: ek/geçici maddeler 'VUK Ek Madde 11' diye etiketlenir — LLM'in normal
    # m.11 ile karıştırmaması + verifier'ın (tur, no) scope'u için kritik.
    tur = str(r.metadata.get("madde_tur") or "madde")
    tur_on_ek = {"ek": "Ek ", "gecici": "Geçici "}.get(tur, "")
    if kod and madde:
        if not madde.isdigit():
            # Yönetmelik chunk'ları (seed_yonetmelik_direct): madde_no ya 'Madde 9 …'
            # metni ya 'chunk-N' placeholder — 'YON_X Madde Madde 9' üretme. Yönetmelik
            # adı payload 'title' alanında (kanun_adi yok).
            base = kanun_adi or (r.metadata.get("title") or "").strip() or kod
            if madde.lower().startswith("madde"):
                return f"{base} {madde}"
            return base
        if kanun_adi:
            return f"{kanun_adi} ({kod}) {tur_on_ek}Madde {madde}"
        return f"{kod} {tur_on_ek}Madde {madde}"
    return r.metadata.get("title") or r.source or r.chunk_id
