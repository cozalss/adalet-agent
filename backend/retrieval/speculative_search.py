"""Spekülatif retrieval — latans garantisi ile kalite iyileştirmesi.

Strateji:
  1. Hybrid search HEMEN başlar (her zaman ~322ms, referans)
  2. HyDE/MQ paralel başlar (potansiyel kalite artışı)
  3. Kullanıcı max SPECULATIVE_DEADLINE_S bekler
  4. HyDE/MQ deadline içinde biterse → kaliteli sonuç
  5. Bitmezse → hybrid sonucu döner (ücretsiz fallback)

Garanti: kullanıcı asla baseline + deadline = ~2.3s'den fazla beklemez.
A/B'de HyDE ortalama 4825ms iken; spekülatif mod ile:
  - Kısa Qwen yanıtı (~2s): HyDE devreye girer → kalite kazanımı
  - Uzun Qwen yanıtı (>2s): hybrid döner → sıfır latans regresyon

Yapılandırma:
    SPECULATIVE_DEADLINE_S (env) = HyDE/MQ için ek bekleme süresi
    default 2.0s → kullanıcı max ~2.3s bekler (baseline 322ms + 2000ms)
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from retrieval.adaptive_router import RoutingDecision
from retrieval.hybrid_search import SearchResult, search  # noqa: F401
from retrieval.hyde import search_with_hyde  # noqa: F401
from retrieval.multi_query import search_multi_query  # noqa: F401

log = structlog.get_logger()


async def search_speculative(
    question: str,
    routing: RoutingDecision,
    top_k: int = 10,
    target_k: int = 32,
    multi_query_n: int = 5,
    hyde_timeout_s: float = 15.0,
    deadline_s: float = 2.0,
) -> tuple[list[Any], str]:
    """Spekülatif arama — latans garantili.

    Args:
        question:      Kullanıcı sorusu
        routing:       Adaptive router kararı (use_hyde, use_mq, domain)
        top_k:         Son sonuç sayısı
        target_k:      HyDE/MQ iç arama genişliği
        multi_query_n: MQ paraphrase sayısı
        hyde_timeout_s: HyDE LLM üretim timeout (hard limit)
        deadline_s:    Hybrid sonrası ek bekleme — kullanıcı latans bütçesi

    Returns:
        (results, strategy_used)
        strategy_used: "hybrid" | "hyde" | "mq" | "hyde+mq" | "hybrid_fallback"
    """
    def _dedup(primary: list, secondary: list) -> list:
        seen: dict = {}
        for r in [*primary, *secondary]:
            if r.chunk_id not in seen:
                seen[r.chunk_id] = r
        return list(seen.values())

    loop = asyncio.get_event_loop()

    # --- 1. Hybrid HEMEN başlat ---
    hybrid_task: asyncio.Task = loop.create_task(
        search(question=question, top_k=target_k, domain=None),
        name="hybrid",
    )

    # --- 2. HyDE / MQ paralel başlat (routing'e göre) ---
    advanced_tasks: dict[str, asyncio.Task] = {}
    if routing.use_hyde:
        advanced_tasks["hyde"] = loop.create_task(
            search_with_hyde(question, top_k=target_k, domain=routing.domain, qdrant_domain=None),
            name="hyde",
        )
    if routing.use_mq:
        advanced_tasks["mq"] = loop.create_task(
            search_multi_query(question, top_k=target_k, n_queries=multi_query_n, domain=None),
            name="mq",
        )

    # Sadece hybrid istendiyse (routing basit → hemen dön)
    if not advanced_tasks:
        results = await hybrid_task
        return results[:top_k], "hybrid"

    # --- 3. Hybrid'i bekle (hızlı) ---
    hybrid_results = await hybrid_task
    t_hybrid = loop.time()

    # --- 4. Deadline kontrolü: advanced task'lar bitti mi? ---
    remaining = []
    done_results: list[Any] = []
    done_keys: list[str] = []

    for key, task in advanced_tasks.items():
        if task.done():
            exc = task.exception()
            if exc is None:
                res = task.result()
                done_results = _dedup(list(res), done_results) if done_results else list(res)
                done_keys.append(key)
            else:
                log.warning("speculative_task_error", key=key, error=str(exc))
                task.cancel()
        else:
            remaining.append((key, task))

    # --- 5. Deadline içinde bitenleri bekle ---
    if remaining:
        wait_left = deadline_s  # kalan bütçe
        if wait_left > 0:
            pending_tasks = [t for _, t in remaining]
            done, pending = await asyncio.wait(
                pending_tasks,
                timeout=wait_left,
                return_when=asyncio.ALL_COMPLETED,
            )
            for task in pending:
                task.cancel()  # deadline doldu, iptal
                log.debug("speculative_deadline_exceeded", timeout_s=deadline_s)
            for task in done:
                exc = task.exception()
                if exc is None:
                    res = task.result()
                    done_results = _dedup(list(res), done_results) if done_results else list(res)
                    # find key by task name
                    for key, t in remaining:
                        if t is task:
                            done_keys.append(key)
                            break
                else:
                    log.warning("speculative_task_error", error=str(exc))
        else:
            # Bütçe zaten tükendi, iptal et
            for _, task in remaining:
                task.cancel()

    # --- 6. Sonuç seç ---
    if done_results:
        # HyDE/MQ en az biri bitti → kaliteli sonuç
        final_results = done_results[:top_k]
        strategy = "+".join(done_keys) if done_keys else "hybrid_fallback"
        log.info(
            "speculative_advanced_win",
            strategy=strategy,
            n_results=len(final_results),
            domain=routing.domain,
        )
        return final_results, strategy

    # Hiçbir advanced task deadline içinde bitmedi → hybrid fallback
    log.info(
        "speculative_hybrid_fallback",
        domain=routing.domain,
        complexity=routing.complexity,
        deadline_s=deadline_s,
    )
    return hybrid_results[:top_k], "hybrid_fallback"
