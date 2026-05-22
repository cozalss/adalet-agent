"""Mini end-to-end seed — gerçek yargi-mcp verisi → BGE-M3 → Qdrant.

Doğrulama adımları:
  1. yargi-mcp'den 3 alan için (tüketici, iş, kira) 3'er karar çek
  2. Her kararın tam metnini fetch et (Markdown)
  3. Chunk'la (1200 char + 200 overlap)
  4. BGE-M3 ile dense + sparse embed et
  5. Qdrant collection'a upsert et
  6. Toplam yazılan chunk sayısını bas

Kullanım:
    uv run python scripts/mini_seed.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from retrieval.chunker import chunk_text
from retrieval.embedding import Embedder
from retrieval.vector_store import (
    ChunkPoint,
    count_points,
    ensure_collection,
    get_client,
    upsert_chunks,
)
from retrieval.yargi_client import YargiClient, YargitayDecision

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("mini_seed")

QUERIES = [
    ("tüketici", "tuketici"),
    ("kıdem tazminatı", "isHukuku"),
    ("kira sözleşmesi", "kira"),
]

PER_QUERY_LIMIT = 3


async def fetch_with_text(
    client: YargiClient,
    decisions: list[YargitayDecision],
) -> list[YargitayDecision]:
    """Karar listelerinde text boşsa get_document ile doldur."""
    enriched: list[YargitayDecision] = []
    for decision in decisions:
        if decision.text or not decision.document_id:
            enriched.append(decision)
            continue
        try:
            text = await client.get_document(decision.document_id)
            if text:
                decision.text = text
        except Exception as exc:
            logger.warning("doc_fetch_failed id=%s err=%s", decision.document_id, exc)
        enriched.append(decision)
    return enriched


async def fetch_all() -> list[tuple[YargitayDecision, str]]:
    """Tüm domainler için kararları çek. (karar, domain) tuple listesi döner."""
    results: list[tuple[YargitayDecision, str]] = []
    async with YargiClient() as client:
        for phrase, domain in QUERIES:
            logger.info("fetching domain=%s phrase=%s", domain, phrase)
            decisions = await client.search_yargitay(phrase, page_number=1)
            decisions = decisions[:PER_QUERY_LIMIT]
            enriched = await fetch_with_text(client, decisions)
            for decision in enriched:
                if decision.text:
                    results.append((decision, domain))
            logger.info("domain=%s | toplam metinli: %d", domain, len(results))
    return results


def build_chunks(
    decisions: list[tuple[YargitayDecision, str]],
    embedder: Embedder,
) -> list[ChunkPoint]:
    """Kararları chunk'la, embed et, ChunkPoint listesine dönüştür."""
    texts: list[str] = []
    metadata: list[dict] = []

    for decision, domain in decisions:
        chunks = chunk_text(decision.text)
        for seq, chunk in enumerate(chunks):
            payload = {
                **decision.to_payload(),
                "chunk_seq": seq,
                "domain": domain,
                "text": chunk,
            }
            chunk_id = f"{decision.id}-c{seq}"
            texts.append(chunk)
            metadata.append({"id": chunk_id, "payload": payload})

    if not texts:
        return []

    logger.info("embedding %d chunks (BGE-M3 ilk seferde ~2 GB iner)...", len(texts))
    started = time.time()
    out = embedder.encode(texts, batch_size=8)
    logger.info("embed bitti: %.1f s", time.time() - started)

    return [
        ChunkPoint(
            id=meta["id"],
            dense_vector=dense,
            sparse_indices=sparse[0],
            sparse_values=sparse[1],
            payload=meta["payload"],
        )
        for meta, dense, sparse in zip(metadata, out.dense, out.sparse)
    ]


async def main() -> int:
    logger.info("=" * 60)
    logger.info("MINI SEED — yargi-mcp → BGE-M3 → Qdrant")
    logger.info("=" * 60)

    decisions = await fetch_all()
    if not decisions:
        logger.error("hiç karar çekilemedi, çıkılıyor")
        return 1

    logger.info("toplam %d karar (metinli) hazır", len(decisions))

    embedder = Embedder()
    chunks = build_chunks(decisions, embedder)
    if not chunks:
        logger.error("hiç chunk üretilmedi")
        return 1

    logger.info("toplam %d chunk Qdrant'a yazılıyor", len(chunks))

    client = get_client()
    try:
        await ensure_collection(client)
        written = await upsert_chunks(client, chunks)
        total = await count_points(client)
    finally:
        await client.close()

    logger.info("=" * 60)
    logger.info("BAŞARILI")
    logger.info("  yazılan chunk: %d", written)
    logger.info("  collection toplam: %d", total)
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
