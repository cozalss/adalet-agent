"""Spekülatif retrieval — sınırlı latans maliyetiyle kalite iyileştirmesi.

Strateji:
  1. Hybrid search HEMEN başlar (baseline — her zaman döndürülecek sonuç)
  2. HyDE/MQ paralel başlar (potansiyel kalite artışı)
  3. Advanced task'lar için bütçe = SPECULATIVE_DEADLINE_S WALL-CLOCK (request başından)
  4. Bütçe içinde biten advanced → kaliteli sonuç; bitmeyenler iptal → hybrid fallback

Latans davranışı (wall-clock bütçe — DİKKAT: "garanti" değil, üst sınır):
    toplam ≤ max(hybrid_ms, deadline_s)
  - hybrid hızlı (örn. 50ms), deadline 2s → advanced'e ~1.95s, tavan 2s
  - hybrid YAVAŞ (örn. 2.5s) → advanced anında iptal, spekülasyon 0 ek maliyet
    → bu durumda toplam = hybrid_ms (baseline kadar; spekülasyon kötüleştirmez)

ÖNEMLİ: hybrid'in kendisinin yavaşlaması (Qdrant GC, embedder cold, CE contention)
toplam süreyi uzatabilir; spekülasyon bunu maskelemez. hybrid_ms ve advanced_ms
ayrı loglanır (speculative_done event) ki darboğaz net görülsün.

Yapılandırma:
    SPECULATIVE_DEADLINE_S (env, default 2.0) = advanced için wall-clock bütçe
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from retrieval.adaptive_router import RoutingDecision
from retrieval.hybrid_search import SearchResult, search  # noqa: F401
from retrieval.hyde import search_with_hyde
from retrieval.multi_query import rrf_merge, search_multi_query

log = structlog.get_logger()


async def search_speculative(  # noqa: C901
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
    # Tamamlanan advanced (HyDE/MQ) sonuç-listeleri burada toplanır; concat YERİNE sonda
    # RRF ile birleştirilir (rank-tabanlı → farklı RRF skor-ölçekleri sorunsuz, ortak isabet
    # öne çıkar). Eski _dedup 'ilk-gören-kazanır' füzyonu kaybediyordu (denetim 2026-06-04).
    collected_lists: list[list] = []

    loop = asyncio.get_event_loop()

    # Wall-clock bütçe: deadline request başından ölçülür, hybrid bitince sıfırlanmaz.
    # Garanti: toplam kullanıcı beklemesi ≤ max(hybrid_ms, deadline_s).
    # - hybrid hızlıysa → advanced'e (deadline_s - hybrid_ms) kalır, tavan deadline_s.
    # - hybrid yavaşsa → advanced anında iptal, spekülasyon 0 ek maliyet getirir.
    t_start = loop.time()

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
            search_multi_query(question, top_k=target_k, n_queries=multi_query_n,
                               domain=None, sparse_domain=routing.domain),
            name="mq",
        )

    # Sadece hybrid istendiyse (routing basit → hemen dön)
    if not advanced_tasks:
        results = await hybrid_task
        hybrid_ms = (loop.time() - t_start) * 1000
        log.info("speculative_done", strategy="hybrid", hybrid_ms=round(hybrid_ms),
                 advanced_ms=0, domain=routing.domain)
        return results[:top_k], "hybrid"

    # --- 3. Hybrid'i bekle (baseline — her zaman döndürülecek) ---
    hybrid_results = await hybrid_task
    hybrid_ms = (loop.time() - t_start) * 1000

    # --- 4. Advanced task'lar zaten bitti mi? ---
    remaining = []
    done_keys: list[str] = []

    for key, task in advanced_tasks.items():
        if task.done():
            exc = task.exception()
            if exc is None:
                collected_lists.append(list(task.result()))
                done_keys.append(key)
            else:
                log.warning("speculative_task_error", key=key, error=str(exc))
                task.cancel()
        else:
            remaining.append((key, task))

    # --- 5. Wall-clock kalan bütçe içinde bitenleri bekle ---
    # KRİTİK: wait_left, hybrid'in TÜKETTİĞİ süreyi düşer. hybrid yavaşsa ≤0 olur
    # ve advanced anında iptal edilir → spekülasyon ek latans getirmez.
    if remaining:
        elapsed_s = loop.time() - t_start
        wait_left = deadline_s - elapsed_s
        if wait_left > 0:
            pending_tasks = [t for _, t in remaining]
            done, pending = await asyncio.wait(
                pending_tasks,
                timeout=wait_left,
                return_when=asyncio.ALL_COMPLETED,
            )
            for task in pending:
                task.cancel()  # bütçe doldu, iptal
            for task in done:
                exc = task.exception()
                if exc is None:
                    collected_lists.append(list(task.result()))
                    for key, t in remaining:
                        if t is task:
                            done_keys.append(key)
                            break
                else:
                    log.warning("speculative_task_error", error=str(exc))
        else:
            # hybrid zaten bütçeyi yedi → advanced'i bekleme, iptal et
            for _, task in remaining:
                task.cancel()
            log.info("speculative_budget_exhausted_by_hybrid",
                     hybrid_ms=round(hybrid_ms), deadline_ms=round(deadline_s * 1000))

    total_ms = (loop.time() - t_start) * 1000
    advanced_ms = round(total_ms - hybrid_ms)

    # --- 6. Sonuç seç ---
    if collected_lists:
        # HyDE/MQ en az biri bütçe içinde bitti → RRF füzyonu (concat değil): farklı
        # skor-ölçekli HyDE/MQ listeleri rank-tabanlı birleşir, ortak isabet öne çıkar.
        final_results = rrf_merge(collected_lists, top_k)
        strategy = "+".join(done_keys) if done_keys else "hybrid_fallback"
        log.info(
            "speculative_done",
            strategy=strategy,
            hybrid_ms=round(hybrid_ms),
            advanced_ms=advanced_ms,
            total_ms=round(total_ms),
            n_results=len(final_results),
            domain=routing.domain,
        )
        return final_results, strategy

    # Hiçbir advanced task bütçe içinde bitmedi → hybrid fallback
    log.info(
        "speculative_done",
        strategy="hybrid_fallback",
        hybrid_ms=round(hybrid_ms),
        advanced_ms=advanced_ms,
        total_ms=round(total_ms),
        domain=routing.domain,
        complexity=routing.complexity,
        deadline_s=deadline_s,
    )
    return hybrid_results[:top_k], "hybrid_fallback"
