"""Canlı emsal fallback (CRAG) — lokal corpus zayıfsa internetten dava çek + LOKAL rerank.

Kök neden (ölçüldü 2026-06-04): lokal emsal corpus bazı domain/alt-konularda zayıf
(tüketici, trafik idari ceza, vergi niş). O sorularda corpus alakasız karar döndürüyordu.

Bu modül: lokal emsal rerank skoru bir eşiğin ALTINDA kalırsa (corpus alakalı dava
bulamadı), domain'e uygun CANLI yargı-mcp kaynağından aday çeker ve **LOKAL reranker**
ile sıralar. KRİTİK: public yargı-mcp relevance-ranking YAPMAZ (tarih-sıralı/gevşek
token-match — ölçüldü); alakayı bizim cross-encoder'ımız verir → upstream'in eksikliği
telafi edilir. Canlı snippet'ler verify pipeline'ından geçer (SIFIR HALÜSİNASYON korunur).

DÜRÜST SINIR: Tüketici Hakem Heyeti kararı yargı-mcp'de YOK → tüketici ayıplı-mal/cayma
gibi sorularda canlı çekme de sınırlı yardım eder. En çok trafik (sigorta_tahkim) ve
vergi (gib_ozelge) gibi keyword-aranabilir özel kaynaklarda fayda sağlar (ölçüldü).

Opt-in: EMSAL_LIVE_FALLBACK_ENABLED=1. Default kapalı (network + latans).
"""

from __future__ import annotations

import asyncio

import structlog

from retrieval.hybrid_search import SearchResult
from retrieval.reranker import get_reranker

log = structlog.get_logger()


def should_trigger_live(question: str, case_results: list) -> tuple[bool, str, float]:
    """Canlı fallback tetiklensin mi? → (tetikle, sinyal_adı, sinyal_değeri).

    Eski sinyal (best CE skoru < EMSAL_LIVE_TRIGGER_SCORE) emsal-bench'te (64 vaka,
    2026-06-10) İKİ yönde bozuk ölçüldü: 24/24 tetikleme yanlış-alarm (CE konuşma-dili
    TR'de noise-floor skor verir) + tek gerçek topikal boşluk 0.802 skorla kaçtı.
    Default mod 'coverage': sorgu içerik-kelimelerinin dönen kararlarca stem-aware
    kapsanması — sorgu kelimeleri kararlarda hiç geçmiyorsa corpus alakasız demektir.
    Bilinen sınır: yanlış ALT-KONU (kapsama yüksek, konu yanlış) bu sinyalle de
    görülemez; o boşluğun çözümü corpus kürasyonu. EMSAL_LIVE_TRIGGER_MODE=score
    eski davranışı geri verir (A/B + geri-uyumluluk).
    """
    from agents.config import (
        EMSAL_LIVE_COVERAGE_MIN,
        EMSAL_LIVE_TRIGGER_MODE,
        EMSAL_LIVE_TRIGGER_SCORE,
    )

    if not case_results:
        return True, "empty", 0.0
    if EMSAL_LIVE_TRIGGER_MODE == "score":
        best = max(float(getattr(r, "score", 0.0)) for r in case_results)
        return best < EMSAL_LIVE_TRIGGER_SCORE, "score", best
    from retrieval.turkish_text import query_coverage
    cov = query_coverage(question, [getattr(r, "text", "") or "" for r in case_results])
    return cov < EMSAL_LIVE_COVERAGE_MIN, "coverage", cov


# Domain → canlı kaynak sırası. Inline-text dönen özel kaynaklar (sigorta_tahkim,
# gib_ozelge, sayistay, kvkk) rerank için ideal; Bedesten (yargitay/danistay) doc-id
# döndürür → top adayların tam metni çekilir (latans için sınırlı).
_DOMAIN_SOURCES: dict[str, tuple[str, ...]] = {
    "trafik": ("sigorta_tahkim", "yargitay"),
    "vergi": ("gib_ozelge", "danistay"),
    "idari": ("danistay", "sayistay"),
    "tuketici": ("yargitay", "kvkk"),
    "kira": ("yargitay",),
    "isHukuku": ("yargitay",),
    "icra": ("yargitay",),
    "tapu": ("yargitay",),
}

# Bedesten (yargitay/danistay) arama doc-id döndürür, metin yok → tam metin çek.
# Latans/rate-limit için yalnız ilk N aday için get_document çağrılır.
_DOC_FETCH_LIMIT = 4


async def _regulator_search(client, source: str, question: str) -> list:
    """Inline-text dönen regülatör/özel kaynak araması (rerank için metin hazır gelir)."""
    if source == "sigorta_tahkim":
        return await client.search_sigorta_tahkim(question, page=1)
    if source == "gib_ozelge":
        return await client.search_gib_ozelge(keywords=question, page=1)
    if source == "sayistay":
        return await client.search_sayistay(question, page=1)
    if source == "kvkk":
        return await client.search_kvkk(question, page=1)
    return []


async def _bedesten_candidates(client, source: str, question: str) -> list[dict]:
    """Bedesten (yargitay/danistay): arama doc-id döndürür → ilk N için tam metin çek."""
    search = client.search_yargitay if source == "yargitay" else client.search_danistay
    decisions = await search(question, page_size=10)
    out: list[dict] = []
    for d in decisions[:_DOC_FETCH_LIMIT]:
        try:
            body = await client.get_document(d.document_id)
        except Exception as exc:
            log.debug("live_doc_fetch_failed", error=str(exc) or type(exc).__name__)
            body = ""
        txt = body or d.summary or d.title or ""
        if txt:
            out.append(_cand(d.id, txt[:2000], source, d.source_url, d.title))
    return out


async def _candidates_from_source(client, source: str, question: str) -> list[dict]:
    """Tek bir canlı kaynaktan rerank'a hazır aday listesi (text dolu) çek."""
    try:
        if source in {"yargitay", "danistay"}:
            return await _bedesten_candidates(client, source, question)
        out: list[dict] = []
        for d in await _regulator_search(client, source, question):
            txt = d.text or d.summary or d.title or ""
            if txt:
                out.append(_cand(d.id, txt, source, d.source_url, d.title))
        return out
    except Exception as exc:
        log.warning("live_source_failed", source=source, error=str(exc) or type(exc).__name__)
        return []


def _cand(doc_id: str, text: str, source: str, url: str | None, title: str | None) -> dict:
    return {
        "chunk_id": doc_id,
        "text": text,
        "source": source,
        "source_url": url or "",
        "domain": "",
        "title": title or doc_id,
    }


async def fetch_and_rank_live(
    question: str,
    domain: str,
    *,
    top_k: int = 5,
    min_score: float = 0.30,
    timeout_s: float = 25.0,
) -> list[SearchResult]:
    """Domain'e uygun canlı kaynaklardan aday çek, LOKAL rerank et, eşik-üstü top_k döndür.

    Network/timeout/parse hatalarında [] döner (çağıran corpus sonucuyla devam eder).
    Eşik-üstü sonuç yoksa [] → dürüst 'emsal bulunamadı' (CLAUDE.md §1, uydurma yok).
    """
    sources = _DOMAIN_SOURCES.get(domain, ("yargitay",))
    try:
        from retrieval.yargi_client import YargiClient
        async with YargiClient() as client:
            cands: list[dict] = []
            for src in sources:
                cands.extend(await _candidates_from_source(client, src, question))
                if len(cands) >= 8:
                    break  # yeterli aday — ek kaynak/latans gereksiz
    except TimeoutError as exc:
        log.warning("live_emsal_timeout", error=str(exc) or type(exc).__name__)
        return []
    except Exception as exc:
        log.warning("live_emsal_failed", error=str(exc) or type(exc).__name__)
        return []

    if not cands:
        log.info("live_emsal_no_candidates", domain=domain)
        return []

    # LOKAL rerank — upstream relevance vermez, alakayı cross-encoder verir.
    reranked = await asyncio.to_thread(get_reranker().rerank, question, cands, top_k)
    kept = [r for r in reranked if r.score >= min_score]
    log.info(
        "live_emsal_done",
        domain=domain, n_candidates=len(cands), n_kept=len(kept),
        top_score=round(reranked[0].score, 3) if reranked else 0.0,
    )
    return [
        SearchResult(
            chunk_id=r.chunk_id, score=r.score, text=r.text, source=r.source,
            source_url=r.source_url, domain=domain, metadata={"live": True, "court": r.source},
        )
        for r in kept
    ]


__all__ = ("fetch_and_rank_live",)
