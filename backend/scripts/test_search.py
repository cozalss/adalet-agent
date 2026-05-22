"""Hybrid search smoke test — Qdrant'taki seed verisi üzerinde arama yapar."""

from __future__ import annotations

import asyncio
import logging
import sys

from retrieval.hybrid_search import search

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("test_search")

QUERIES = [
    ("İşten haksız yere çıkarıldım, kıdem tazminatımı nasıl alırım?", None),
    ("Tüketici hakem heyetine başvuru süresi nedir?", "tuketici"),
    ("Ev sahibim kontratımı yenilemek istemiyor, ne yapabilirim?", "kira"),
]


async def main() -> int:
    logger.info("=" * 70)
    logger.info("HYBRID SEARCH TEST — Qdrant'taki seed verisinde arama")
    logger.info("=" * 70)

    for question, domain in QUERIES:
        logger.info("\nSORU: %s", question)
        if domain:
            logger.info("Filtre: domain=%s", domain)

        results = await search(question, top_k=3, domain=domain)
        if not results:
            logger.warning("  → SONUÇ YOK")
            continue

        logger.info("  → %d sonuç:", len(results))
        for i, r in enumerate(results, start=1):
            chamber = r.metadata.get("chamber") or "-"
            date = r.metadata.get("date") or "-"
            snippet = r.text.replace("\n", " ")[:140]
            logger.info(
                "  %d. score=%.3f | %s | %s | %s",
                i,
                r.score,
                r.domain or "-",
                chamber,
                date,
            )
            logger.info("     %s...", snippet)

    logger.info("\n" + "=" * 70)
    logger.info("TEST TAMAM")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
