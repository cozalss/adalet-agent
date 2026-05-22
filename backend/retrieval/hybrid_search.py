"""Hybrid search — BGE-M3 dense + sparse, Qdrant RRF fusion.

Ajan veya API katmanı bu modülü çağırır. Tek bir public fonksiyon:
    search(question, top_k=5, domain=None) → list[SearchResult]

Performans hedefi: < 500 ms tek sorgu (embed + Qdrant + payload).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from qdrant_client import models

from .embedding import Embedder
from .vector_store import COLLECTION_NAME, get_client

log = structlog.get_logger()


@dataclass(slots=True)
class SearchResult:
    chunk_id: str
    score: float
    text: str
    source: str
    source_url: str
    domain: str
    metadata: dict[str, Any]


_embedder_singleton: Embedder | None = None


def _get_embedder() -> Embedder:
    global _embedder_singleton
    if _embedder_singleton is None:
        _embedder_singleton = Embedder()
    return _embedder_singleton


async def search(
    question: str,
    top_k: int = 5,
    prefetch_limit: int = 50,
    domain: str | None = None,
) -> list[SearchResult]:
    """Hybrid search — dense + sparse prefetch, RRF fusion, ilk top_k sonuç.

    Args:
        question: Kullanıcı sorusu.
        top_k: Döndürülecek sonuç sayısı.
        prefetch_limit: Her vektör için ilk aşamada çekilecek aday sayısı.
        domain: Filtre — None ise tüm domainler.
    """
    if not question.strip():
        return []

    embedder = _get_embedder()
    dense_vec, (sparse_idx, sparse_val) = embedder.encode_query(question)

    query_filter = None
    if domain:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="domain",
                    match=models.MatchValue(value=domain),
                )
            ]
        )

    client = get_client()
    try:
        result = await client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(
                    query=dense_vec,
                    using="dense",
                    limit=prefetch_limit,
                    filter=query_filter,
                ),
                models.Prefetch(
                    query=models.SparseVector(indices=sparse_idx, values=sparse_val),
                    using="sparse",
                    limit=prefetch_limit,
                    filter=query_filter,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
    finally:
        await client.close()

    return [_to_result(point) for point in result.points]


def _to_result(point: Any) -> SearchResult:
    payload = point.payload or {}
    chunk_id = payload.get("chunk_id") or str(point.id)
    return SearchResult(
        chunk_id=chunk_id,
        score=float(point.score) if point.score is not None else 0.0,
        text=payload.get("text", ""),
        source=payload.get("source", ""),
        source_url=payload.get("source_url", ""),
        domain=payload.get("domain", ""),
        metadata={
            k: v
            for k, v in payload.items()
            if k not in {"text", "source", "source_url", "domain", "chunk_id"}
        },
    )
