"""Fetch stage — DecisionRef akışını tam metinle zenginleştirir.

Skip-on-error pattern: tek karar fail olursa run durmaz, state'e kaydedilir.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from .config import DomainConfig
from .metrics import RunStats
from .rate_limiter import AsyncTokenBucket
from .sources import DecisionRef, DecisionSource, EmptyDocumentError
from .state import SeedState

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EnrichedDecision:
    """DecisionRef + tam metin — pipeline'a giren paket."""

    ref: DecisionRef
    text: str
    domain: str


async def stream_decisions(
    source: DecisionSource,
    domain: DomainConfig,
    state: SeedState,
    rate: AsyncTokenBucket,
    limit: int,
    stats: RunStats,
) -> AsyncIterator[EnrichedDecision]:
    """Domain anahtar kelimelerini sırayla tara, tam metinli kararları yield et.

    - `limit` toplam hedef: state'te zaten X doc varsa, bu run en fazla (limit-X) yield eder.
    - Daha önce işlenmiş doc_id'ler iter_refs'e skip_ids olarak verilir → fetch yok.
    - Fetch hataları (timeout, HTTP, boş metin) loglanır + state'e error kaydı.
    - KeyboardInterrupt / CancelledError yakalanmaz, propagate edilir.
    """
    skip_ids = state.load()
    already_done = len(skip_ids)

    if already_done >= limit:
        logger.info(
            "fetch_skip_all",
            extra={
                "court": source.court_id,
                "domain": domain.name,
                "already_done": already_done,
                "limit": limit,
            },
        )
        return

    target_new = limit - already_done
    yielded_this_run = 0

    # Sprint-5 W13: Daire filtreleri (chambers) opsiyonel.
    # Domain için bu court'un chambers'ı tanımlıysa, her keyword × her chamber
    # ayrı API call → coverage artar. Aksi halde tek-pass (chamber=None).
    court_chambers: tuple[str | None, ...]
    if domain.chambers and source.court_id in domain.chambers:
        court_chambers = tuple(domain.chambers[source.court_id])
    else:
        court_chambers = (None,)

    logger.info(
        "fetch_started",
        extra={
            "court": source.court_id,
            "domain": domain.name,
            "already_done": already_done,
            "target_new": target_new,
            "chambers": court_chambers,
        },
    )

    for keyword in domain.keywords:
        if yielded_this_run >= target_new:
            break

        for chamber in court_chambers:
            if yielded_this_run >= target_new:
                break

            remaining = target_new - yielded_this_run
            logger.info(
                "fetch_keyword_started",
                extra={
                    "keyword": keyword,
                    "chamber": chamber,
                    "remaining": remaining,
                },
            )

            async for ref in source.iter_refs(keyword, remaining, rate, skip_ids, chamber=chamber):
                try:
                    text = await source.fetch_text(ref, rate)
                except (
                    EmptyDocumentError,
                    httpx.HTTPError,
                    httpx.TimeoutException,
                    ValueError,
                    RuntimeError,
                ) as exc:
                    logger.warning(
                        "doc_fetch_failed",
                        extra={"doc_id": ref.doc_id, "err": str(exc)[:200]},
                    )
                    state.mark_done(ref.doc_id, status="error", reason=type(exc).__name__)
                    skip_ids.add(ref.doc_id)
                    stats.errors += 1
                    continue
                except (KeyboardInterrupt, asyncio.CancelledError):
                    raise

                yielded_this_run += 1
                yield EnrichedDecision(ref=ref, text=text, domain=domain.name)

                if yielded_this_run >= target_new:
                    break
