"""Law-chunk ColBERT vektörlerini önceden hesapla → yan Qdrant collection (MAX_SIM).

NEDEN: colbert-rerank (BGE-M3 compute_score) passage'ları HER sorguda yeniden encode ediyor
(~30 forward) → CPU'da ~15s latency → demo'da kapalı. Law chunk'lar corpus'un %4.6'sı (7,338)
→ colbert vektörlerini ÖNCEDEN hesaplayıp sakla → rerank = sorgu-colbert (1 forward) + Qdrant
MAX_SIM (filter=candidate chunk_id) → passage-forward YOK → hızlı + deployable.

Yan collection (ana adalet_mursit_hybrid'e DOKUNMAZ): yalnız colbert multivector + chunk_id payload.
INT8 quant → ~1.1GB. Rerank-time: query_points(using='colbert', query_filter=chunk_id∈candidates).

Çalıştırma (GPU, backend durdurulmuş olmalı → GPU boş):
    (set -a; source .env; set +a; EMBEDDING_DEVICE=cuda uv run python -m scripts.seed_law_colbert)
"""
from __future__ import annotations

import asyncio
import logging
import os

from qdrant_client import models

from core import native_preload  # noqa: F401  pyarrow'u torch'tan önce yükle (Windows)
from retrieval.embedding import Embedder
from retrieval.vector_store import COLLECTION_NAME, get_client

log = logging.getLogger("scripts.seed_law_colbert")

COLBERT_COLLECTION = os.getenv("COLBERT_COLLECTION", "adalet_law_colbert")
_COLBERT_DIM = 1024  # BGE-M3 colbert token-vektör boyutu
_BATCH = 64          # encode batch (GPU-verimli)
_MAX_TOK = 512       # colbert token cap — compute-path ile EŞLE (cap-256 madde_recall'u 40.9→34.8
                     # düşürmüştü, uzun maddeleri truncate ediyordu). 512 → pure-colbert ~40.9%.
_UPSERT_SUB = 3      # upsert alt-batch (cap-512 → payload ~2x; Qdrant REST 33MB/istek limiti)


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s", datefmt="%H:%M:%S")
    client = get_client()

    # BGE-M3 embedder (colbert için) — SPARSE_EMBEDDER_MODEL'den bağımsız, explicit bge-m3.
    embedder = Embedder(os.getenv("COLBERT_RERANK_MODEL", "BAAI/bge-m3"))
    embedder.ensure_loaded()
    log.info("colbert_embedder_ready")

    # 1. Yan collection (varsa sil + yeniden — idempotent seed).
    if await client.collection_exists(COLBERT_COLLECTION):
        await client.delete_collection(COLBERT_COLLECTION)
    await client.create_collection(
        collection_name=COLBERT_COLLECTION,
        vectors_config={
            "colbert": models.VectorParams(
                size=_COLBERT_DIM,
                distance=models.Distance.COSINE,
                multivector_config=models.MultiVectorConfig(comparator=models.MultiVectorComparator.MAX_SIM),
                # token-vektörlerine HNSW gereksiz (rerank filter'la → exact); index kapalı, RAM tasarrufu.
                hnsw_config=models.HnswConfigDiff(m=0),
            ),
        },
        # INT8 quant KALDIRILDI: ColBERT MAX_SIM precision-hassas; INT8 madde_recall'u 42→35%
        # düşürmüştü (baseline altı). fp32 (~4GB, feasible) → +5.2pp korunur, latency ~aynı.
        on_disk_payload=False,
    )
    await client.create_payload_index(
        COLBERT_COLLECTION, field_name="chunk_id", field_schema=models.PayloadSchemaType.KEYWORD,
    )
    log.info("colbert_collection_created name=%s", COLBERT_COLLECTION)

    # 2. Ana collection'dan law chunk'larını scroll et (chunk_id + text) → batch encode → upsert.
    total = 0
    next_off = None
    while True:
        points, next_off = await client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=models.Filter(must=[models.FieldCondition(key="doc_type", match=models.MatchValue(value="law"))]),
            limit=_BATCH, offset=next_off, with_payload=["chunk_id", "text"], with_vectors=False,
        )
        if not points:
            break
        ids = [p.id for p in points]
        chunk_ids = [(p.payload or {}).get("chunk_id") or str(p.id) for p in points]
        texts = [(p.payload or {}).get("text") or "" for p in points]
        out = await asyncio.to_thread(embedder.encode, texts, _BATCH, _MAX_TOK, True)  # return_colbert=True
        cb = out.colbert or []
        upserts = [
            models.PointStruct(id=pid, vector={"colbert": vecs}, payload={"chunk_id": cid})
            for pid, cid, vecs in zip(ids, chunk_ids, cb, strict=True) if vecs
        ]
        # Qdrant REST 33MB/istek limiti → colbert payload (T×1024) büyük; küçük alt-batch'le upsert.
        for i in range(0, len(upserts), _UPSERT_SUB):
            sub = upserts[i : i + _UPSERT_SUB]
            await client.upsert(collection_name=COLBERT_COLLECTION, points=sub, wait=False)
            total += len(sub)
        log.info("colbert_seeded batch=%d total=%d", len(upserts), total)
        if next_off is None:
            break
    log.info("colbert_seed_done total=%d collection=%s", total, COLBERT_COLLECTION)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
