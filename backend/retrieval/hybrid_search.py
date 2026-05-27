"""Hybrid search — BGE-M3 dense + sparse (+ opsiyonel ColBERT), Qdrant RRF fusion.

Sprint-4 ile 3-kol prefetch desteği eklendi:
  1. dense        (BGE-M3 1024-d cosine)
  2. sparse       (BM25 IDF)
  3. colbert      (token MAX_SIM late-interaction)   — opsiyonel

Run-time'da collection ColBERT vec içeriyorsa 3-kol; yoksa 2-kol çalışır.
Caller hiç değişiklik yapmadan eski API ile çalışır.

Tek public fonksiyon:
    search(question, top_k=5, domain=None) → list[SearchResult]

Cross-encoder rerank için:
    search_with_rerank(question, top_k=5, candidates_n=50, domain=None)
        → list[RerankResult]

Performans hedefi: < 700 ms tek sorgu (embed + Qdrant + payload, ColBERT açık).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import structlog
from qdrant_client import models

from .embedding import Embedder
from .reranker import RerankResult, get_reranker
from .vector_store import COLLECTION_NAME, collection_has_colbert, get_shared_client

log = structlog.get_logger()

# Run-time ColBERT toggle — false ise schema'da olsa bile sorguda kullanma
COLBERT_QUERY_ENABLED = os.getenv("COLBERT_QUERY_ENABLED", "1").lower() in {"1", "true", "yes"}


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
_colbert_supported_cache: bool | None = None


def _get_embedder() -> Embedder:
    global _embedder_singleton
    if _embedder_singleton is None:
        _embedder_singleton = Embedder()
    return _embedder_singleton


async def _detect_colbert_support(client) -> bool:
    """Bir kez kontrol et + cache'le; her sorguda Qdrant'a sormak istemiyoruz."""
    global _colbert_supported_cache
    if _colbert_supported_cache is None:
        _colbert_supported_cache = await collection_has_colbert(client)
    return _colbert_supported_cache


def _reset_colbert_cache() -> None:
    """Test/migration sonrası reset."""
    global _colbert_supported_cache
    _colbert_supported_cache = None


async def search(
    question: str,
    top_k: int = 5,
    prefetch_limit: int = 50,
    domain: str | None = None,
) -> list[SearchResult]:
    """Hybrid search — dense + sparse (+ ColBERT) prefetch, RRF fusion, top_k.

    Args:
        question: Kullanıcı sorusu.
        top_k: Döndürülecek sonuç sayısı.
        prefetch_limit: Her vektör için ilk aşamada çekilecek aday sayısı.
        domain: Filtre — None ise tüm domainler.
    """
    if not question.strip():
        return []

    # Paylaşılan client — kapatma (process-ömürlü singleton).
    client = get_shared_client()
    colbert_supported = await _detect_colbert_support(client)
    want_colbert = COLBERT_QUERY_ENABLED and colbert_supported

    embedder = _get_embedder()
    # to_thread: BGE-M3 forward CPU/GPU-bound — event loop'u bloke etme.
    dense_vec, (sparse_idx, sparse_val), colbert_vecs = await embedder.aencode_query(
        question, return_colbert=want_colbert,
    )

    query_filter = _build_filter(domain)

    prefetch_list: list[models.Prefetch] = [
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
    ]
    if want_colbert and colbert_vecs:
        prefetch_list.append(
            models.Prefetch(
                query=colbert_vecs,  # multi-vector list[list[float]]
                using="colbert",
                limit=prefetch_limit,
                filter=query_filter,
            )
        )

    result = await client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=prefetch_list,
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=top_k,
        with_payload=True,
    )

    return [_to_result(point) for point in result.points]


async def search_with_rerank(
    question: str,
    top_k: int = 5,
    candidates_n: int = 50,
    domain: str | None = None,
) -> list[RerankResult]:
    """İki aşamalı pipeline: hybrid → cross-encoder rerank → top_k.

    Args:
        question: Kullanıcı sorusu.
        top_k: Final sonuç sayısı (varsayılan 5).
        candidates_n: Reranker'a gönderilecek aday sayısı (varsayılan 50).
        domain: Filtre — None ise tüm domainler.

    Returns:
        Cross-encoder relevance score'a göre sıralanmış RerankResult listesi.
    """
    candidates = await search(
        question=question,
        top_k=candidates_n,
        prefetch_limit=candidates_n,
        domain=domain,
    )
    if not candidates:
        return []

    reranker = get_reranker()
    return await asyncio.to_thread(reranker.rerank, question, candidates, top_k)


def _build_filter(domain: str | None) -> models.Filter | None:
    if not domain:
        return None
    return models.Filter(
        must=[
            models.FieldCondition(
                key="domain",
                match=models.MatchValue(value=domain),
            )
        ]
    )


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
