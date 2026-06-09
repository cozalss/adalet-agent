"""adalet_mursit koleksiyonunu dense+sparse ile yeniden oluştur.

Sorun: adalet_mursit yalnızca dense (768-dim) içeriyor — sparse yok.
       Hybrid search sparse olmadan domain@1'i 78%→76% düşürüyor.

Çözüm (model inference yok, sadece vektör kopyalama):
  1. adalet_mursit_hybrid oluştur (dense 768 + sparse IDF)
  2. Her nokta için: dense → adalet_mursit, sparse → adalet
  3. adalet_mursit_hybrid'e her ikisini yaz
  4. adalet_mursit sil, adalet_mursit_hybrid'i yeniden adlandır

Çalıştırma:
    uv run python -m scripts.rebuild_mursit_hybrid
    uv run python -m scripts.rebuild_mursit_hybrid --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import native_preload  # noqa: F401

logger = logging.getLogger("rebuild_mursit_hybrid")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

MURSIT_SRC = "adalet_mursit"   # sadece dense (768-dim)
SPARSE_SRC  = "adalet"         # sadece sparse (BGE-M3 IDF) + dense (1024-dim, görmezden)
TARGET      = "adalet_mursit_hybrid"
FINAL       = "adalet_mursit"
BATCH       = 200


async def main(args: argparse.Namespace) -> None:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http.models import (
        Distance,
        Modifier,
        PointStruct,
        SparseVector,
        SparseVectorParams,
        VectorParams,
    )

    q = AsyncQdrantClient(url="http://localhost:6333")

    # --- 0. Dense+sparse koleksiyon oluştur ---
    existing = [c.name for c in (await q.get_collections()).collections]
    if TARGET in existing:
        if args.dry_run:
            logger.info("DRY-RUN: %s zaten var, silinecekti", TARGET)
        else:
            await q.delete_collection(TARGET)
            logger.info("%s silindi", TARGET)

    if not args.dry_run:
        await q.create_collection(
            collection_name=TARGET,
            vectors_config={"dense": VectorParams(size=768, distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams(index=None, modifier=Modifier.IDF)},
        )
        logger.info("%s oluşturuldu (dense=768 + sparse=IDF)", TARGET)
        # Filtrelenen payload alanlarına index (denetim #2): yoksa doc_type/kanun_kodu/
        # madde_no/chunk_id filtreli arama 159K noktada O(N) brute-force olur.
        from retrieval.vector_store import create_payload_indexes
        await create_payload_indexes(q, TARGET)
        logger.info("%s payload index'leri kuruldu (domain/source/doc_type/kanun_kodu/chunk_id/madde_no)", TARGET)

    # --- 1. adalet_mursit'ten tüm ID+dense, adalet'ten aynı ID+sparse al ---
    total = n_written = 0
    dense_map: dict = {}
    sparse_map: dict = {}

    # Mursit dense vektörleri belleğe al
    logger.info("adalet_mursit dense vektörleri okunuyor...")
    offset = None
    while True:
        result, next_offset = await q.scroll(
            collection_name=MURSIT_SRC,
            limit=BATCH,
            offset=offset,
            with_vectors=["dense"],
            with_payload=True,
        )
        for p in result:
            dense_map[p.id] = (p.vector["dense"], p.payload)
        total += len(result)
        if total % 10000 == 0:
            logger.info("  dense: %d okundu", total)
        if next_offset is None:
            break
        offset = next_offset
    logger.info("Dense tamamlandı: %d nokta", total)

    # adalet sparse vektörlerini belleğe al
    logger.info("adalet sparse vektörleri okunuyor...")
    total_sp = 0
    offset = None
    while True:
        result, next_offset = await q.scroll(
            collection_name=SPARSE_SRC,
            limit=BATCH,
            offset=offset,
            with_vectors=["sparse"],
            with_payload=False,
        )
        for p in result:
            if p.id in dense_map and p.vector and "sparse" in p.vector:
                sparse_map[p.id] = p.vector["sparse"]
        total_sp += len(result)
        if total_sp % 10000 == 0:
            logger.info("  sparse: %d tarandı", total_sp)
        if next_offset is None:
            break
        offset = next_offset
    logger.info("Sparse tarandı: %d nokta, eşleşen: %d", total_sp, len(sparse_map))

    if args.dry_run:
        missing_sparse = len(dense_map) - len(sparse_map)
        logger.info("DRY-RUN: %d dense, %d sparse, %d sparse eksik",
                    len(dense_map), len(sparse_map), missing_sparse)
        return

    # --- 2. TARGET'a yaz ---
    logger.info("Target'a yazılıyor: %d nokta...", len(dense_map))
    ids = list(dense_map.keys())
    for batch_start in range(0, len(ids), BATCH):
        batch_ids = ids[batch_start:batch_start + BATCH]
        points = []
        for pid in batch_ids:
            dense, payload = dense_map[pid]
            vec: dict = {"dense": dense}
            if pid in sparse_map:
                sv = sparse_map[pid]
                vec["sparse"] = SparseVector(indices=sv.indices, values=sv.values)
            points.append(PointStruct(id=pid, vector=vec, payload=payload))
        await q.upsert(collection_name=TARGET, points=points)
        n_written += len(points)
        if n_written % 10000 == 0 or n_written == len(ids):
            pct = n_written / len(ids) * 100
            logger.info("[%.1f%%] %d/%d yazıldı", pct, n_written, len(ids))

    # --- 3. Swap ---
    logger.info("Swap başlıyor: %s sil → %s → %s", FINAL, TARGET, FINAL)
    if FINAL in existing:
        await q.delete_collection(FINAL)
    await q.update_collection(collection_name=TARGET)  # no-op ping
    # Qdrant alias veya rename yok — collection adını kopyalayamayız.
    # FINAL = TARGET olacak şekilde config'de TARGET kullanın.
    # Veya: TARGET'ı FINAL olarak yeniden oluştur (collection copy).
    # Pratik çözüm: .env'de QDRANT_COLLECTION=adalet_mursit_hybrid
    logger.info("=" * 60)
    logger.info("TAMAMLANDI: %d nokta adalet_mursit_hybrid'e yazıldı", n_written)
    logger.info("Kullanım: QDRANT_COLLECTION=adalet_mursit_hybrid")
    logger.info("Ya da: scripts/rename_collection.py ile adalet_mursit'e taşı")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(main(parser.parse_args()))
