"""Qdrant vector store — collection management + upsert.

Hybrid search için named vectors kullanır:
- "dense": BGE-M3 1024-dim cosine
- "sparse": BM25 sparse vectors

Hybrid sorgu için `retrieval/hybrid_search.py` modülüne bak.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient, models

log = structlog.get_logger()

COLLECTION_NAME = "adalet"
DENSE_VECTOR_SIZE = 1024  # BGE-M3 boyutu
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None

# Deterministic UUID üretimi için sabit namespace.
# Aynı chunk_id her zaman aynı UUID'yi verir → idempotent upsert.
_CHUNK_UUID_NAMESPACE = uuid.UUID("8c5e4a14-9b1c-4f2a-8a6f-1d2e3b4c5a6b")


def chunk_id_to_uuid(chunk_id: str) -> str:
    """String chunk ID → deterministic UUID5 string."""
    return str(uuid.uuid5(_CHUNK_UUID_NAMESPACE, chunk_id))


@dataclass(slots=True)
class ChunkPoint:
    """Qdrant'a yazılacak tek chunk."""

    id: str
    dense_vector: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]
    payload: dict[str, Any]


def get_client() -> AsyncQdrantClient:
    return AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


async def ensure_collection(client: AsyncQdrantClient) -> None:
    """Collection yoksa hybrid yapılandırma ile oluştur. Varsa dokunma."""
    existing = await client.get_collections()
    if any(c.name == COLLECTION_NAME for c in existing.collections):
        log.info("collection_exists", name=COLLECTION_NAME)
        return

    await client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": models.VectorParams(
                size=DENSE_VECTOR_SIZE,
                distance=models.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(
                modifier=models.Modifier.IDF,
            ),
        },
        hnsw_config=models.HnswConfigDiff(m=16, ef_construct=128),
    )

    await client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="domain",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )
    await client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="source",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )

    log.info("collection_created", name=COLLECTION_NAME, size=DENSE_VECTOR_SIZE)


async def upsert_chunks(
    client: AsyncQdrantClient,
    chunks: list[ChunkPoint],
    batch_size: int = 64,
) -> int:
    """Chunk batch'lerini Qdrant'a yaz. Toplam yazılan sayı döner.

    Qdrant point ID'leri integer veya UUID olmak zorunda — string chunk_id
    her zaman UUID5 ile deterministic bir UUID'ye dönüştürülür. Orijinal
    chunk_id payload'da `chunk_id` field'ı olarak saklanır.
    """
    written = 0
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        points = [
            models.PointStruct(
                id=chunk_id_to_uuid(chunk.id),
                vector={
                    "dense": chunk.dense_vector,
                    "sparse": models.SparseVector(
                        indices=chunk.sparse_indices,
                        values=chunk.sparse_values,
                    ),
                },
                payload={**chunk.payload, "chunk_id": chunk.id},
            )
            for chunk in batch
        ]
        await client.upsert(collection_name=COLLECTION_NAME, points=points)
        written += len(batch)
        log.debug("batch_upserted", count=len(batch), total=written)

    log.info("upsert_completed", total=written)
    return written


async def count_points(client: AsyncQdrantClient) -> int:
    """Collection'daki toplam nokta sayısı."""
    info = await client.count(collection_name=COLLECTION_NAME, exact=True)
    return info.count
