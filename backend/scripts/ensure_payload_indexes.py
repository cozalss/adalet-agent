"""Önceden seed edilmiş Qdrant koleksiyonuna eksik payload index'lerini ekle (migration).

Denetim #2 (2026-06-09 worldclass-audit): production koleksiyonu `adalet_mursit_hybrid`
yalnız domain+source indexli kuruldu (rebuild_mursit_hybrid create_collection index kurmuyordu).
hybrid_search ise doc_type/kanun_kodu/madde_no/chunk_id üzerinde de filtreliyor → bu alanlar
indexsiz olduğundan filtreli her sorgu 159K noktayı O(N) brute-force tarıyor.

Bu script idempotent'tir (zaten-var index'i atlar). YENİ koleksiyonlar ensure_collection /
rebuild_mursit_hybrid ile zaten indexli gelir; bu yalnız MEVCUT koleksiyonu düzeltir.

Çalıştırma (Qdrant çalışır olmalı):
    uv run python -m scripts.ensure_payload_indexes
    uv run python -m scripts.ensure_payload_indexes --collection adalet_mursit_hybrid
    uv run python -m scripts.ensure_payload_indexes --url http://localhost:6333
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import native_preload  # noqa: F401

logger = logging.getLogger("ensure_payload_indexes")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")


async def main(args: argparse.Namespace) -> None:
    from qdrant_client import AsyncQdrantClient

    from retrieval.vector_store import _PAYLOAD_INDEXES, create_payload_indexes

    client = AsyncQdrantClient(url=args.url)
    try:
        existing = [c.name for c in (await client.get_collections()).collections]
        if args.collection not in existing:
            logger.error("Koleksiyon yok: %s (mevcut: %s)", args.collection, existing)
            sys.exit(1)

        fields = ", ".join(f for f, _ in _PAYLOAD_INDEXES)
        logger.info("Index'ler sağlanıyor → %s: %s", args.collection, fields)
        # skip_existing=True: zaten kurulu index'ler atlanır (idempotent).
        await create_payload_indexes(client, args.collection, skip_existing=True)
        logger.info("Tamam — filtreli arama artık index kullanır (O(N) brute-force bitti).")
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", default="adalet_mursit_hybrid", help="Hedef koleksiyon")
    parser.add_argument("--url", default="http://localhost:6333", help="Qdrant URL")
    asyncio.run(main(parser.parse_args()))
