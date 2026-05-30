"""adalet → adalet_mursit delta senkronizasyonu.

adalet'te olup adalet_mursit'te olmayan chunk'ları Mursit ile embed eder
ve adalet_mursit'e ekler. Seed sonrası çalıştırın.

Çalıştırma:
    uv run python -m scripts.sync_mursit_delta
    uv run python -m scripts.sync_mursit_delta --dry-run  # ne ekleyeceğini göster
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import native_preload  # noqa: F401

logger = logging.getLogger("sync_mursit")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

SOURCE = "adalet"
TARGET = os.getenv("QDRANT_COLLECTION", "adalet_mursit_hybrid")
BATCH_SIZE = 64
SCROLL_BATCH = 500


async def main(args: argparse.Namespace) -> None:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http.models import PointStruct
    from sentence_transformers import SentenceTransformer

    q = AsyncQdrantClient(url="http://localhost:6333")

    # adalet_mursit'teki mevcut ID'leri belirle (hızlı delta)
    logger.info("adalet_mursit ID'leri yükleniyor...")
    existing_ids: set = set()
    offset = None
    while True:
        result, next_offset = await q.scroll(
            collection_name=TARGET,
            limit=SCROLL_BATCH,
            offset=offset,
            with_vectors=False,
            with_payload=False,
        )
        for p in result:
            existing_ids.add(p.id)
        if next_offset is None:
            break
        offset = next_offset
    logger.info("Mevcut adalet_mursit: %d nokta", len(existing_ids))

    # adalet'ten eksik olanları çek
    missing = []
    offset = None
    while True:
        result, next_offset = await q.scroll(
            collection_name=SOURCE,
            limit=SCROLL_BATCH,
            offset=offset,
            with_vectors=False,
            with_payload=True,
        )
        for p in result:
            if p.id not in existing_ids:
                missing.append(p)
        if next_offset is None:
            break
        offset = next_offset

    logger.info("Delta: %d yeni nokta adalet_mursit'e eklenecek", len(missing))

    if args.dry_run or not missing:
        if missing:
            logger.info("DRY-RUN: ilk 5 → %s", [p.id for p in missing[:5]])
        return

    # Mursit modeli yükle
    logger.info("Mursit yükleniyor...")
    model = SentenceTransformer("newmindai/Mursit-Base-TR-Retrieval", trust_remote_code=True)
    logger.info("Mursit hazır.")

    # adalet'ten sparse vektörleri de çek (hybrid koleksiyon için)
    logger.info("adalet sparse vektörleri okunuyor (hybrid için)...")
    missing_ids = {p.id for p in missing}
    sparse_map: dict = {}
    offset = None
    while True:
        result, next_offset = await q.scroll(
            collection_name=SOURCE,
            limit=SCROLL_BATCH,
            offset=offset,
            with_vectors=["sparse"],
            with_payload=False,
        )
        for p in result:
            if p.id in missing_ids and p.vector and "sparse" in p.vector:
                sparse_map[p.id] = p.vector["sparse"]
        if next_offset is None:
            break
        offset = next_offset
    logger.info("Sparse okundu: %d/%d eşleşti", len(sparse_map), len(missing))

    n_added = 0
    for batch_start in range(0, len(missing), BATCH_SIZE):
        batch = missing[batch_start:batch_start + BATCH_SIZE]
        texts = [p.payload.get("text", "") or p.payload.get("snippet", "") for p in batch]
        vecs = model.encode(texts, batch_size=BATCH_SIZE, convert_to_numpy=True, show_progress_bar=False)

        from qdrant_client.http.models import SparseVector
        points = []
        for p, v in zip(batch, vecs):
            vec: dict = {"dense": v.tolist()}
            if p.id in sparse_map:
                sv = sparse_map[p.id]
                vec["sparse"] = SparseVector(indices=sv.indices, values=sv.values)
            points.append(PointStruct(id=p.id, vector=vec, payload=p.payload))
        await q.upsert(collection_name=TARGET, points=points)
        n_added += len(points)

        if n_added % 1000 == 0 or n_added == len(missing):
            pct = n_added / len(missing) * 100
            logger.info("[%.1f%%] %d/%d eklendi", pct, n_added, len(missing))

    logger.info("Delta sync tamamlandı: %d yeni nokta eklendi", n_added)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(main(parser.parse_args()))
