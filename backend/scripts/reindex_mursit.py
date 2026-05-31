"""Mursit-Base ile Qdrant koleksiyonunu yeniden index et.

Mevcut 'adalet' koleksiyonunu (BGE-M3, 1024-dim) okur,
her chunk'ı Mursit-Base-TR-Retrieval (768-dim) ile yeniden embed eder
ve 'adalet_mursit' koleksiyonuna yazar.

Mursit neden?
  Embedding kalite testi (2026-05-30): Mursit, BGE-M3'e göre ortalama +151% daha
  iyi relevant/irrelevant ayrımı yapıyor. trafik: +306%, isHukuku: +101%.

Çalıştırma:
    LLM_MODE=llamacpp_server uv run python -m scripts.reindex_mursit
    LLM_MODE=llamacpp_server uv run python -m scripts.reindex_mursit --dry-run --limit 500
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import native_preload  # noqa: F401

logger = logging.getLogger("reindex_mursit")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

SOURCE_COLLECTION = "adalet"
TARGET_COLLECTION = "adalet_mursit"
MURSIT_MODEL = "newmindai/Mursit-Base-TR-Retrieval"
MURSIT_DIM = 768
BATCH_SIZE = 64
SCROLL_LIMIT = 500


def _load_mursit():
    from sentence_transformers import SentenceTransformer
    logger.info("Mursit yükleniyor: %s", MURSIT_MODEL)
    model = SentenceTransformer(MURSIT_MODEL, trust_remote_code=True)
    logger.info("Mursit yüklendi (768-dim)")
    return model


def _embed_batch(model, texts: list[str]) -> list[list[float]]:
    vecs = model.encode(texts, batch_size=BATCH_SIZE, convert_to_numpy=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]


async def _ensure_mursit_collection(qdrant) -> None:
    from qdrant_client.http.models import Distance, VectorParams

    existing = [c.name for c in (await qdrant.get_collections()).collections]
    if TARGET_COLLECTION in existing:
        logger.info("Koleksiyon zaten var: %s", TARGET_COLLECTION)
        return

    await qdrant.create_collection(
        collection_name=TARGET_COLLECTION,
        vectors_config={"dense": VectorParams(size=MURSIT_DIM, distance=Distance.COSINE)},
    )
    logger.info("Koleksiyon oluşturuldu: %s (dim=%d)", TARGET_COLLECTION, MURSIT_DIM)


async def _scroll_all(qdrant, limit: int | None = None):
    """Source koleksiyondan tüm noktaları çek."""
    all_points = []
    offset = None

    while True:
        result, next_offset = await qdrant.scroll(
            collection_name=SOURCE_COLLECTION,
            limit=SCROLL_LIMIT,
            offset=offset,
            with_vectors=False,
            with_payload=True,
        )
        all_points.extend(result)
        if limit and len(all_points) >= limit:
            all_points = all_points[:limit]
            break
        if next_offset is None:
            break
        offset = next_offset
        if len(all_points) % 5000 == 0:
            logger.info("Çekildi: %d nokta", len(all_points))

    return all_points


async def main(args: argparse.Namespace) -> None:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http.models import PointStruct

    qdrant = AsyncQdrantClient(url="http://localhost:6333")

    # 1. Hedef koleksiyonu oluştur
    if not args.dry_run:
        await _ensure_mursit_collection(qdrant)

    # 2. Tüm noktaları çek
    logger.info("Source koleksiyondan noktalar çekiliyor: %s", SOURCE_COLLECTION)
    t0 = time.perf_counter()
    points = await _scroll_all(qdrant, limit=args.limit)
    logger.info("Çekildi: %d nokta (%.1fs)", len(points), time.perf_counter() - t0)

    # 3. Mursit modelini yükle
    model = _load_mursit()

    # 4. Batch embed + insert
    logger.info("Embedding başlıyor...")
    n_inserted = 0
    texts = [p.payload.get("text", "") or p.payload.get("snippet", "") for p in points]

    for batch_start in range(0, len(points), BATCH_SIZE):
        batch_pts = points[batch_start:batch_start + BATCH_SIZE]
        batch_texts = texts[batch_start:batch_start + BATCH_SIZE]

        if not any(batch_texts):
            continue

        vecs = _embed_batch(model, batch_texts)

        if not args.dry_run:
            qdrant_points = [
                PointStruct(
                    id=p.id,
                    vector={"dense": vec},
                    payload=p.payload,
                )
                for p, vec in zip(batch_pts, vecs)
            ]
            await qdrant.upsert(collection_name=TARGET_COLLECTION, points=qdrant_points)

        n_inserted += len(batch_pts)
        if n_inserted % 2000 == 0 or n_inserted == len(points):
            pct = n_inserted / len(points) * 100
            elapsed = time.perf_counter() - t0
            logger.info("[%5.1f%%] %d/%d nokta — %.0fs geçti", pct, n_inserted, len(points), elapsed)

    elapsed_total = time.perf_counter() - t0
    logger.info("Tamamlandı: %d nokta, %.0fs", n_inserted, elapsed_total)

    if args.dry_run:
        logger.info("DRY-RUN: Hiçbir şey yazılmadı.")
        return

    # 5. Kontrol
    info = await qdrant.get_collection(TARGET_COLLECTION)
    logger.info("Koleksiyon %s: %d nokta", TARGET_COLLECTION, info.points_count)
    logger.info("Sıradaki adım: QDRANT_COLLECTION=adalet_mursit ile benchmark çalıştır")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Qdrant'a yazmadan test et")
    parser.add_argument("--limit", type=int, default=None, help="Max nokta sayısı (test için)")
    asyncio.run(main(parser.parse_args()))
