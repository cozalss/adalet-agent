"""Qdrant vector store — collection management + upsert.

Hybrid search için named vectors kullanır:
  - "dense"   : BGE-M3 1024-dim cosine
  - "sparse"  : BM25 sparse vectors (IDF modifier)
  - "colbert" : (opsiyonel) ColBERT multi-vector MAX_SIM late-interaction

ColBERT field — Sprint-4 W1 itibariyle **production default ON** (`COLBERT_ENABLED=1`).
Yeni collection oluştururken `colbert` named vector schema'sı eklenir; eski
collection ColBERT vec içermiyorsa hybrid_search runtime'da `collection_has_colbert`
ile tespit edip 2-kol (dense+sparse) çalışır. ColBERT'i mevcut collection'a
eklemek için reseed gerekir (`scripts/seed_mevzuat.py` ile drop + recreate).

Hybrid sorgu için `retrieval/hybrid_search.py` modülüne bak.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient, models

log = structlog.get_logger()

COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "adalet")
DENSE_VECTOR_SIZE = 1024  # BGE-M3 dense boyutu
COLBERT_VECTOR_SIZE = 1024  # BGE-M3 ColBERT token vec boyutu
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None

# Schema-level ColBERT toggle (collection oluştururken kullanılır)
COLBERT_ENABLED = os.getenv("COLBERT_ENABLED", "1").lower() in {"1", "true", "yes"}

# Deterministic UUID üretimi için sabit namespace — idempotent upsert.
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
    # ColBERT opsiyonel — token başına bir vektör listesi
    colbert_vectors: list[list[float]] | None = field(default=None)


def get_client() -> AsyncQdrantClient:
    """Her çağrıda YENİ client. Kısa-ömürlü işler (seed/build/eval script'leri)
    için — onlar kendi lifecycle'larını yönetip `await client.close()` eder."""
    return AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)


# EMBEDDING_MODEL adı → ürettiği dense vektör boyutu. Startup fail-fast için.
_EMBEDDER_DIMS: dict[str, int] = {
    "BAAI/bge-m3": 1024,
    "newmindai/Mursit-Base-TR-Retrieval": 768,
    "newmindai/Mursit-Large-TR-Retrieval": 1024,
}


def _expected_embedder_dim(model_name: str) -> int | None:
    """Bilinen model için dense boyutu; bilinmiyorsa None (assert atlanır)."""
    for known, dim in _EMBEDDER_DIMS.items():
        if model_name.startswith(known):
            return dim
    return None


async def assert_collection_dim(client: AsyncQdrantClient | None = None) -> None:
    """Startup fail-fast: EMBEDDING_MODEL boyutu ≠ koleksiyon boyutu ise patla.

    Sessiz production bug'ını (768-dim model × 1024-dim koleksiyon) boot'ta
    görünür hata yapar. Koleksiyon yoksa veya model bilinmiyorsa sessizce geçer
    (seed henüz yapılmamış olabilir).
    """
    model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    expected = _expected_embedder_dim(model_name)
    if expected is None:
        log.warning("collection_dim_check_skipped", reason="unknown_model", model=model_name)
        return

    owns_client = client is None
    client = client or get_client()
    try:
        existing = [c.name for c in (await client.get_collections()).collections]
        if COLLECTION_NAME not in existing:
            log.warning("collection_dim_check_skipped",
                        reason="collection_absent", collection=COLLECTION_NAME)
            return
        info = await client.get_collection(COLLECTION_NAME)
        vectors = info.config.params.vectors
        # named vector dict ("dense") veya tek VectorParams olabilir
        actual = vectors["dense"].size if isinstance(vectors, dict) else vectors.size
        if actual != expected:
            raise RuntimeError(
                f"BOYUT UYUŞMAZLIĞI: EMBEDDING_MODEL={model_name} {expected}-dim üretir "
                f"ama QDRANT_COLLECTION={COLLECTION_NAME} {actual}-dim. "
                f"Doğru koleksiyonu set et veya modeli değiştir."
            )
        log.info("collection_dim_ok", model=model_name, collection=COLLECTION_NAME, dim=actual)
    finally:
        if owns_client:
            await client.close()


# Process-ömürlü paylaşılan client — request path (hybrid_search/hyde) için.
# Eskiden her search çağrısı yeni client+pool açıp finally'de kapatıyordu →
# her /ask'ta TCP/gRPC handshake churn'ü. Tek client'ı yeniden kullan.
_shared_client: AsyncQdrantClient | None = None


def get_shared_client() -> AsyncQdrantClient:
    """Process boyunca yeniden kullanılan tek Qdrant client (lazy init).

    Request path için: bağlantı havuzu churn'ünü önler. KAPATMA — singleton;
    `main.py` lifespan shutdown'ında `aclose_shared_client()` ile kapanır.
    """
    global _shared_client
    if _shared_client is None:
        _shared_client = AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _shared_client


async def aclose_shared_client() -> None:
    """Paylaşılan client'ı kapat + sıfırla (lifespan shutdown). Idempotent."""
    global _shared_client
    if _shared_client is not None:
        client, _shared_client = _shared_client, None
        await client.close()


def _reset_shared_client() -> None:
    """Test izolasyonu — singleton referansını sıfırla (kapatmadan)."""
    global _shared_client
    _shared_client = None


async def collection_has_colbert(client: AsyncQdrantClient) -> bool:
    """Mevcut collection ColBERT vec destekliyor mu? Run-time tespiti."""
    try:
        info = await client.get_collection(collection_name=COLLECTION_NAME)
    except Exception:
        return False
    vectors = info.config.params.vectors or {}
    if isinstance(vectors, dict):
        return "colbert" in vectors
    return False


# Filtrelenen TÜM payload alanları indexlenmeli; yoksa filtreli arama O(N) brute-force
# olur (159K noktada her doc_type/kanun_kodu/madde_no/chunk_id filtreli sorgu tüm
# koleksiyonu tarar → "lokal/hızlı" tez direğini çürüten darboğaz). Denetim #2 (2026-06-09).
# Tip ÖNEMLİ: madde_no payload'da int (chunker `int(...)`) → INTEGER; geri kalan str → KEYWORD.
_PAYLOAD_INDEXES: tuple[tuple[str, models.PayloadSchemaType], ...] = (
    ("domain", models.PayloadSchemaType.KEYWORD),
    ("source", models.PayloadSchemaType.KEYWORD),
    ("doc_type", models.PayloadSchemaType.KEYWORD),
    ("kanun_kodu", models.PayloadSchemaType.KEYWORD),
    ("chunk_id", models.PayloadSchemaType.KEYWORD),
    ("madde_no", models.PayloadSchemaType.INTEGER),
    # P8 (2026-06-11): madde_tur (madde|ek|gecici) — fetch_maddeler must_not +
    # gold-validator + verify filtreleri bu alanı kullanır.
    ("madde_tur", models.PayloadSchemaType.KEYWORD),
)


async def create_payload_indexes(
    client: AsyncQdrantClient,
    collection_name: str = COLLECTION_NAME,
    *,
    skip_existing: bool = False,
) -> None:
    """Filtrelenen payload alanlarına index oluştur.

    Yeni koleksiyonda ensure_collection bunu çağırır. ÖNCEDEN seed edilmiş koleksiyonlar
    (ör. production `adalet_mursit_hybrid`) için migration olarak da kullanılır.

    Args:
        skip_existing: True → zaten-var hatası yutulur (idempotent migration); False → propagate.
    """
    for field_name, schema in _PAYLOAD_INDEXES:
        try:
            await client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=schema,
            )
        except Exception as exc:  # migration idempotency: zaten-var hatasını yut
            if not skip_existing:
                raise
            log.info("payload_index_skip", field=field_name, err=str(exc))


async def ensure_collection(
    client: AsyncQdrantClient,
    enable_colbert: bool | None = None,
) -> None:
    """Collection yoksa hybrid yapılandırma ile oluştur. Varsa dokunma.

    Args:
        enable_colbert: True → ColBERT multi-vector field eklenir.
                        None → COLBERT_ENABLED env'ine göre.
    """
    existing = await client.get_collections()
    if any(c.name == COLLECTION_NAME for c in existing.collections):
        log.info("collection_exists", name=COLLECTION_NAME)
        return

    want_colbert = COLBERT_ENABLED if enable_colbert is None else enable_colbert

    vectors_config: dict[str, models.VectorParams] = {
        "dense": models.VectorParams(
            size=DENSE_VECTOR_SIZE,
            distance=models.Distance.COSINE,
        ),
    }
    if want_colbert:
        # ColBERT late-interaction — multi-vector MAX_SIM
        vectors_config["colbert"] = models.VectorParams(
            size=COLBERT_VECTOR_SIZE,
            distance=models.Distance.COSINE,
            multivector_config=models.MultiVectorConfig(
                comparator=models.MultiVectorComparator.MAX_SIM,
            ),
            # ColBERT vec'leri büyük — disk'te tut, RAM'de tutma
            on_disk=True,
        )

    await client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=vectors_config,
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(
                modifier=models.Modifier.IDF,
            ),
        },
        hnsw_config=models.HnswConfigDiff(m=16, ef_construct=128),
    )

    await create_payload_indexes(client, COLLECTION_NAME)

    log.info(
        "collection_created",
        name=COLLECTION_NAME,
        size=DENSE_VECTOR_SIZE,
        colbert=want_colbert,
    )


async def upsert_chunks(
    client: AsyncQdrantClient,
    chunks: list[ChunkPoint],
    batch_size: int = 64,
) -> int:
    """Chunk batch'lerini Qdrant'a yaz. Toplam yazılan sayı döner.

    ColBERT vec'i mevcutsa chunk'ta `colbert_vectors` ile gönder; yoksa
    yalnız dense + sparse upsert edilir (mevcut collection'larla uyumlu).
    """
    written = 0
    has_colbert_col = await collection_has_colbert(client)

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        points: list[models.PointStruct] = []
        for chunk in batch:
            vector_map: dict[str, Any] = {
                "dense": chunk.dense_vector,
                "sparse": models.SparseVector(
                    indices=chunk.sparse_indices,
                    values=chunk.sparse_values,
                ),
            }
            if has_colbert_col and chunk.colbert_vectors:
                vector_map["colbert"] = chunk.colbert_vectors

            points.append(
                models.PointStruct(
                    id=chunk_id_to_uuid(chunk.id),
                    vector=vector_map,
                    payload={**chunk.payload, "chunk_id": chunk.id},
                )
            )
        await client.upsert(collection_name=COLLECTION_NAME, points=points)
        written += len(batch)
        log.debug("batch_upserted", count=len(batch), total=written)

    log.info("upsert_completed", total=written, colbert=has_colbert_col)
    return written


async def count_points(client: AsyncQdrantClient) -> int:
    """Collection'daki toplam nokta sayısı."""
    info = await client.count(collection_name=COLLECTION_NAME, exact=True)
    return info.count
