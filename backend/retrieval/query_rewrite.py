"""Step-back query rewrite (1.1) — konuşma-dili sorgu → resmî hukuki kavram köprüsü.

Kök sorun (ölçülmüş): doğru kanun havuza geliyor (kanun@5=0.83) ama doğru MADDE üst
sıraya çıkamıyor (madde_recall@5=0.35). Cross-encoder reranker'a giren sorgu KONUŞMA-DİLİ
olduğu için doğru maddeyi aşağı itiyor ("ranking-reversal"). HyDE hipotetik CEVAP üretir;
step-back farklıdır: SORGUYU resmî hukuki terimlere/kuruma yeniden yazar (kavramsal yükseltme),
böylece hem retrieval hem RERANKER resmî dille çalışır.

Tasarım (opt-in, QUERY_REWRITE_ENABLED, default 0):
  - Yalnız KONUŞMA-DİLİ sorgularda tetiklenir (adaptive_router complexity eşiği).
  - 1 hızlı LOKAL LLM çağrısı tek bir resmî rewrite üretir (madde/kanun UYDURMAZ).
  - Orijinal + rewrite ayrı aranıp RRF ile birleşir → EN KÖTÜ DURUM = baseline
    (orijinal sonuçlar her zaman havuzda). Rewrite ayrıca rerank sorgusu olarak da
    kullanılabilir (mevzuat_node).
  - Kullanıcıya GÖSTERİLMEZ (hipotetik değil, retrieval-içi kavramsal köprü).

SOTA: step-back (Springer İtalyan-hukuk-RAG: her domende en yüksek doğruluk),
Qwen3-Reranker raporu: reranker'a girmeden ÖNCE colloquial gürültüyü temizle.
"""

from __future__ import annotations

import asyncio
import json
import os
import re

import httpx
import structlog

from agents.llm import ChatMessage, get_llm
from retrieval.hybrid_search import SearchResult, search
from retrieval.multi_query import rrf_merge

log = structlog.get_logger()

# Call-time env (VERIFY_STRICT deseni) → testler monkeypatch.setenv ile toggle eder.
_LLM_FALLBACK_EXCEPTIONS = (asyncio.TimeoutError, httpx.HTTPError, ConnectionError)
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

_STEP_BACK_SYSTEM = (
    "Sen bir Türk hukuku terim asistanısın. Vatandaşın günlük dille sorduğu soruyu, "
    "hukuki belge aramasında kullanılacak RESMÎ bir arama cümlesine çevir: ilgili hukuki "
    "kavramları, kurumları ve terimleri adlandır. Madde numarası veya kanun adı UYDURMA — "
    "yalnız konuyu hukuki terimlerle yeniden ifade et.\n\n"
    "Örnek: 'ev sahibim depozitomu geri vermiyor' → "
    "'kira sözleşmesi sona erdiğinde depozito (güvence bedeli) iadesi, kiracının iade talebi'\n"
    "Örnek: 'işten çıkarıldım param ödenmedi' → "
    "'iş sözleşmesinin feshi, işçinin kıdem ve ihbar tazminatı alacağı'\n\n"
    "Çıktı SADECE şu JSON, başka metin YOK:\n"
    '{"rewrite": "resmî arama cümlesi"}'
)

_STEP_BACK_USER = "Hukuk alanı: {domain}\nVatandaş sorusu: {question}\n\nSADECE JSON döndür."


def is_query_rewrite_enabled() -> bool:
    """Step-back rewrite açık mı (opt-in, default 0). Call-time → test toggle edilebilir."""
    return os.getenv("QUERY_REWRITE_ENABLED", "0").lower() in {"1", "true", "yes"}


def should_rewrite(question: str, domain: str) -> bool:
    """Sorgu konuşma-dili mi (rewrite'tan yararlanır mı)? Kanun-referanslı/çok kısa → hayır.

    adaptive_router complexity skorunu yeniden kullanır (DRY); QUERY_COMPLEXITY_THRESHOLD
    altındaki spesifik sorgular zaten resmî → rewrite gereksiz (latans israfı).
    """
    if not is_query_rewrite_enabled():
        return False
    from agents.config import QUERY_COMPLEXITY_THRESHOLD
    from retrieval.adaptive_router import _query_complexity
    return _query_complexity(question) >= QUERY_COMPLEXITY_THRESHOLD


def _timeout_s() -> float:
    # 12s default: E2E (2026-06-04, in-process Qwen 14B) 6s'te 2/3 çağrı TimeoutError
    # verdi (step-back ekstra serial LLM çağrısı; cold/meşgul modelde 6s yetmiyor).
    # Server modunda paralel → daha hızlı; in-process için 12s makul. 0 = devre dışı.
    return float(os.getenv("QUERY_REWRITE_TIMEOUT_S", "12.0"))


def _max_tokens() -> int:
    return int(os.getenv("QUERY_REWRITE_MAX_TOKENS", "120"))


def _parse_rewrite(raw: str) -> str:
    """{"rewrite": "..."} JSON'dan rewrite metnini çıkar; geçersizse boş döner."""
    if not raw:
        return ""
    cleaned = _JSON_FENCE_RE.sub("", raw).strip()
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        first, last = cleaned.find("{"), cleaned.rfind("}")
        if first == -1 or last <= first:
            return ""
        try:
            obj = json.loads(cleaned[first : last + 1])
        except json.JSONDecodeError:
            return ""
    if not isinstance(obj, dict):
        return ""
    rewrite = obj.get("rewrite", "")
    return rewrite.strip() if isinstance(rewrite, str) else ""


async def step_back_query(question: str, domain: str | None = None) -> str:
    """Konuşma-dili soruyu resmî hukuki arama cümlesine çevir (1 LLM çağrısı).

    LLM hata/timeout/boş → "" döner (caller orijinalle devam eder, baseline güvenli).
    Madde/kanun UYDURMAZ — yalnız konuyu hukuki terimlerle yeniden ifade eder.
    """
    question = question.strip()
    if not question:
        return ""
    user_msg = _STEP_BACK_USER.format(domain=domain or "genel hukuk", question=question)
    llm = get_llm()
    try:
        resp = await asyncio.wait_for(
            llm.chat(
                messages=[
                    ChatMessage(role="system", content=_STEP_BACK_SYSTEM),
                    ChatMessage(role="user", content=user_msg),
                ],
                temperature=0.0,
                max_tokens=_max_tokens(),
                json_mode=True,
            ),
            timeout=_timeout_s(),
        )
    except _LLM_FALLBACK_EXCEPTIONS as exc:
        log.warning("step_back_llm_failed", error=str(exc) or type(exc).__name__)
        return ""
    rewrite = _parse_rewrite(resp.content)
    if rewrite and rewrite.lower() != question.lower():
        log.info("step_back_rewrite", domain=domain, rewrite=rewrite[:120])
        return rewrite
    return ""


# ---------------------------------------------------------------------------
# Konuşma decontextualization (multi-turn) — takip sorusu → bağımsız hukuki sorgu
# ---------------------------------------------------------------------------
# Ölçülmüş bug: "kıdem şartları" → iyi cevap; takip "peki 1 yıldan az çalıştıysam"
# → REDDEDİLİYOR (ham takip metni hukuki çıpa içermez → zayıf chunk → grounding yok).
# Çözüm: chat_history ile takip sorusunu bağımsız hale getir, retrieval'da onu kullan.
# triaj._CONTINUATION_MARKERS ile aynı markerlar (kopya — retrieval→agents cycle riski yok).
_FOLLOWUP_MARKERS = (
    "peki", "o zaman", "bu durumda", "böyle", "şöyle", "öyleyse",
    "ya da", "bunun için", "buna göre", "o halde",
)

# RED-LINE: nötr soru kipi — uygunluk SONUCU ("alır/alamaz") UYDURMAZ; yalnız adıl/eksilti
# çözer + konuyu hukuki terimle ifade eder. "1 yıldan az" → "...hak kazanır mı?" (soru), ASLA
# "...kazanamaz" (çıkarım). Madde/kanun/içtihat uydurmaz (step-back ile aynı kısıt).
_DECONTEXT_SYSTEM = (
    "Sen Türkçe hukuk sorularını BAĞIMSIZ hale getiren bir yardımcısın. Kullanıcının takip "
    "sorusunu ve önceki konuşmayı alır; takip sorusunu, geçmiş bilinmeden de anlaşılır TARAFSIZ "
    "bir hukuki SORUYA çevirirsin.\n\n"
    "KURALLAR:\n"
    "1. Yalnız adıl/eksiltiyi çöz (önceki konuyla birleştir). SONUÇ veya KISITLAMA UYDURMA.\n"
    "   YANLIŞ: '1 yıldan az çalışan işçi kıdem tazminatı ALAMAZ, ne yapmalı?'\n"
    "   DOĞRU:  '1 yıldan az çalışan işçi kıdem tazminatına hak kazanır mı?'\n"
    "2. Madde numarası, kanun adı veya içtihat UYDURMA — yalnız konuyu hukuki terimlerle ifade et.\n"
    "3. Orijinal sorunun çerçevesini koru; soru dışı bilgi ekleme.\n"
    'Çıktı SADECE şu JSON, başka metin YOK:\n{"rewrite": "bağımsız hukuki soru"}'
)

_DECONTEXT_USER = "Önceki konuşma:\n{history}\n\nTakip sorusu: {question}\n\nSADECE JSON döndür."


def is_conv_decontext_enabled() -> bool:
    """Konuşma decontextualization açık mı (opt-in, default 0). Call-time → test toggle."""
    return os.getenv("CONV_DECONTEXT_ENABLED", "0").lower() in {"1", "true", "yes"}


def _is_followup(question: str) -> bool:
    """Bağlam-bağımlı takip sorusu mu (triaj._is_continuation ile aynı markerlar)."""
    q = question.replace("İ", "i").replace("I", "ı").lower().strip()
    return any(q.startswith(m) or f" {m}" in q[:30] for m in _FOLLOWUP_MARKERS)


async def decontextualize_for_retrieval(
    question: str, chat_history: list, domain: str | None = None
) -> str:
    """Takip sorusunu bağımsız hukuki sorguya çevir; RETRIEVAL'da kullanılacak sorguyu döndür.

    Etkin değilse / geçmiş yoksa / takip sorusu değilse / LLM başarısızsa → ORİJİNAL question
    (baseline, güvenli hata). RED-LINE: _DECONTEXT_SYSTEM nötr soru kipini zorlar (uygunluk
    sonucu uydurmaz). Orijinal soru draft'a state["question"] ile gider; bu yalnız retrieval içindir.
    """
    q = (question or "").strip()
    if not q or not is_conv_decontext_enabled() or not chat_history or not _is_followup(q):
        return q
    recent = chat_history[-3:]
    hist = "\n".join(
        f"{'Kullanıcı' if (t.get('role') == 'user') else 'Asistan'}: {str(t.get('content', ''))[:300]}"
        for t in recent
    )
    user_msg = _DECONTEXT_USER.format(history=hist, question=q)
    llm = get_llm()
    try:
        resp = await asyncio.wait_for(
            llm.chat(
                messages=[
                    ChatMessage(role="system", content=_DECONTEXT_SYSTEM),
                    ChatMessage(role="user", content=user_msg),
                ],
                temperature=0.0,
                max_tokens=_max_tokens(),
                json_mode=True,
            ),
            timeout=_timeout_s(),
        )
    except Exception as exc:  # SÖZLEŞME: herhangi bir hata → orijinal sorgu (baseline).
        # _LLM_FALLBACK_EXCEPTIONS'tan GENİŞ bilinçli: in-process llama.cpp RuntimeError/
        # KeyError/CancelledError de fırlatabilir; dar catch bunları node'un except'ine
        # kaçırıp retrieval'ı TAMAMEN boşaltıyordu (adversarial MEDIUM). Geniş catch → baseline.
        log.warning("decontext_llm_failed", error=str(exc) or type(exc).__name__)
        return q
    rewrite = _parse_rewrite(resp.content)
    if rewrite and rewrite.lower() != q.lower():
        log.info("decontext_rewrite", domain=domain, original=q[:60], rewrite=rewrite[:120])
        return rewrite
    return q


async def search_with_step_back(
    question: str,
    *,
    top_k: int = 10,
    per_query_k: int = 30,
    domain: str | None = None,
    sparse_domain: str | None = None,
    doc_type: str | list[str] | None = None,
) -> tuple[list[SearchResult], str]:
    """Orijinal + step-back rewrite'ı ayrı arayıp RRF ile birleştir.

    Returns:
        (merged_results, rewrite). rewrite "" ise yalnız orijinal arama yapıldı
        (baseline davranış birebir). rewrite varsa downstream rerank sorgusu olarak
        da kullanılabilir (mevzuat_node). RRF → orijinal sonuçlar her zaman havuzda
        kalır (en kötü durum baseline).
    """
    rewrite = await step_back_query(question, domain)
    if not rewrite:
        results = await search(
            question=question, top_k=per_query_k, prefetch_limit=per_query_k,
            domain=domain, sparse_domain=sparse_domain, doc_type=doc_type,
        )
        return results[:top_k], ""

    orig_task = search(
        question=question, top_k=per_query_k, prefetch_limit=per_query_k,
        domain=domain, sparse_domain=sparse_domain, doc_type=doc_type,
    )
    rw_task = search(
        question=rewrite, top_k=per_query_k, prefetch_limit=per_query_k,
        domain=domain, sparse_domain=sparse_domain, doc_type=doc_type,
    )
    done = await asyncio.gather(orig_task, rw_task, return_exceptions=True)
    valid: list[list[SearchResult]] = []
    for r in done:
        if isinstance(r, BaseException):
            log.warning("step_back_search_failed", error=str(r) or type(r).__name__)
            continue
        valid.append(r)
    if not valid:
        return [], rewrite
    return rrf_merge(valid, top_k), rewrite


__all__ = (
    "decontextualize_for_retrieval",
    "is_conv_decontext_enabled",
    "is_query_rewrite_enabled",
    "search_with_step_back",
    "should_rewrite",
    "step_back_query",
)
