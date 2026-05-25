"""Streaming batch pipeline — fetch → chunk → embed → upsert → mark state.

RAM cap: batch_chunks (örn. 100) × ~50 KB = ~5 MB peak.
Embedder ve Qdrant client tek seferde inşa edilir, batch'ler arası yeniden kullanılır.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient

from retrieval.chunker import chunk_text
from retrieval.embedding import Embedder
from retrieval.vector_store import ChunkPoint, upsert_chunks

from .config import DomainConfig, SeedConfig
from .fetch import EnrichedDecision, stream_decisions
from .metrics import RunStats
from .rate_limiter import AsyncTokenBucket
from .sources import DecisionSource
from .state import SeedState

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _PendingChunk:
    """Embed öncesi geçici buffer kaydı."""

    chunk_text: str
    chunk_id: str
    payload: dict[str, Any]
    doc_id: str


async def run_pipeline(
    cfg: SeedConfig,
    source: DecisionSource,
    domain_config: DomainConfig,
    embedder: Embedder,
    qdrant: AsyncQdrantClient,
    state: SeedState,
    rate: AsyncTokenBucket,
    stats: RunStats,
) -> None:
    """Tek bir (court, domain) için seed çalıştır."""
    pending: list[_PendingChunk] = []
    pending_doc_ids: set[str] = set()
    pending_doc_chunk_counts: dict[str, int] = {}

    async for enriched in stream_decisions(
        source=source,
        domain=domain_config,
        state=state,
        rate=rate,
        limit=cfg.limit_per_domain,
        stats=stats,
    ):
        stats.fetched += 1
        doc_chunks = _build_pending_chunks(enriched, source.court_id)
        if not doc_chunks:
            state.mark_done(
                enriched.ref.doc_id,
                status="skipped",
                reason="no_chunks",
            )
            continue

        pending.extend(doc_chunks)
        pending_doc_ids.add(enriched.ref.doc_id)
        pending_doc_chunk_counts[enriched.ref.doc_id] = len(doc_chunks)

        if len(pending) >= cfg.batch_chunks:
            await _flush_batch(
                pending=pending,
                pending_doc_ids=pending_doc_ids,
                pending_doc_chunk_counts=pending_doc_chunk_counts,
                cfg=cfg,
                embedder=embedder,
                qdrant=qdrant,
                state=state,
                stats=stats,
            )
            pending = []
            pending_doc_ids = set()
            pending_doc_chunk_counts = {}

    # Son flush
    if pending:
        await _flush_batch(
            pending=pending,
            pending_doc_ids=pending_doc_ids,
            pending_doc_chunk_counts=pending_doc_chunk_counts,
            cfg=cfg,
            embedder=embedder,
            qdrant=qdrant,
            state=state,
            stats=stats,
        )


def _build_pending_chunks(
    enriched: EnrichedDecision,
    court_id: str,
) -> list[_PendingChunk]:
    """Bir kararı chunk'lara böl, _PendingChunk listesine dönüştür."""
    chunks = chunk_text(enriched.text)
    out: list[_PendingChunk] = []

    base_payload = {
        "doc_id": enriched.ref.doc_id,
        "court": court_id,
        "chamber": enriched.ref.chamber,
        "date": enriched.ref.date,
        "title": enriched.ref.title,
        "source": court_id,
        "source_url": enriched.ref.source_url,
        "domain": enriched.domain,
    }

    for seq, chunk in enumerate(chunks):
        chunk_id = f"{enriched.ref.doc_id}-c{seq}"
        payload = {**base_payload, "chunk_seq": seq, "text": chunk}
        out.append(
            _PendingChunk(
                chunk_text=chunk,
                chunk_id=chunk_id,
                payload=payload,
                doc_id=enriched.ref.doc_id,
            )
        )
    return out


async def _flush_batch(
    *,
    pending: list[_PendingChunk],
    pending_doc_ids: set[str],
    pending_doc_chunk_counts: dict[str, int],
    cfg: SeedConfig,
    embedder: Embedder,
    qdrant: AsyncQdrantClient,
    state: SeedState,
    stats: RunStats,
) -> None:
    """Bekleyen chunk'ları embed et + upsert et + state'e mark_done."""
    if not pending:
        return

    texts = [pc.chunk_text for pc in pending]
    logger.debug("flushing_batch", extra={"chunks": len(texts), "docs": len(pending_doc_ids)})

    # BGE-M3 CPU/GPU-bound — event loop'u tıkamamak için thread'e at.
    out = await asyncio.to_thread(embedder.encode, texts, 8)
    stats.embedded += len(texts)

    points = [
        ChunkPoint(
            id=pc.chunk_id,
            dense_vector=dense,
            sparse_indices=sparse[0],
            sparse_values=sparse[1],
            payload=pc.payload,
        )
        for pc, dense, sparse in zip(pending, out.dense, out.sparse)
    ]

    if cfg.dry_run:
        logger.info("dry_run_skip_upsert", extra={"chunks": len(points)})
    else:
        # NOT: upsert_chunks tüm batch'i tek seferde gönderir. Hata olursa
        # exception propagate olur ve mark_done HİÇ çağrılmaz — yani bu
        # batch'teki bütün dokümanlar resume'da yeniden fetch+embed edilir.
        # Bu kabul edilebilir: batch_chunks=100 / ~7 chunk/doc → max ~14 doc
        # tekrarı. Daha ince granularite için ayrı upsert per-doc gerekirdi.
        await upsert_chunks(qdrant, points)

    # CRITICAL: state.mark_done sadece upsert başarılı olduktan sonra
    target = cfg.limit_per_domain
    for doc_id in pending_doc_ids:
        chunk_count = pending_doc_chunk_counts.get(doc_id, 0)
        state.mark_done(doc_id, status="ok", chunks=chunk_count)
        stats.upserted_docs += 1
        stats.upserted_chunks += chunk_count
        stats.log_if_due(cfg.progress_every, target)
