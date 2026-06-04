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


async def search_with_step_back(
    question: str,
    *,
    top_k: int = 10,
    per_query_k: int = 30,
    domain: str | None = None,
    sparse_domain: str | None = None,
    doc_type: str | None = None,
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
    "is_query_rewrite_enabled",
    "search_with_step_back",
    "should_rewrite",
    "step_back_query",
)
