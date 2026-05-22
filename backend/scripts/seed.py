"""Bulk seeding script — Yargıtay + mevzuat → BGE-M3 embed → Qdrant.

Akış:
  1. yargi-mcp'den Yargıtay kararlarını çek (domain bazında)
  2. mevzuat.gov.tr'den ilgili kanunları çek
  3. Metinleri chunk'la
  4. BGE-M3 ile dense + sparse embed et
  5. Qdrant collection'a upsert et

Kullanım:
    uv run python scripts/seed.py --domain tuketici --limit 1000
    uv run python scripts/seed.py --domain all --limit 5000 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Iterable, Literal

import structlog

from retrieval.chunker import chunk_mevzuat, chunk_text
from retrieval.embedding import Embedder
from retrieval.mevzuat_client import KANUN_KODU_TO_NUMARA, Madde, MevzuatClient
from retrieval.vector_store import (
    ChunkPoint,
    count_points,
    ensure_collection,
    get_client,
    upsert_chunks,
)
from retrieval.yargi_client import YargiClient, YargitayDecision

log = structlog.get_logger()

Domain = Literal["tuketici", "isHukuku", "kira", "all"]

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "tuketici": ["tüketici", "ayıplı mal", "garanti", "iade"],
    "isHukuku": ["işçi", "kıdem tazminatı", "ihbar tazminatı", "haksız fesih"],
    "kira": ["kira sözleşmesi", "tahliye", "kiracı", "kira artışı"],
}

DOMAIN_KANUNLAR: dict[str, list[str]] = {
    "tuketici": ["TKHK"],
    "isHukuku": ["IK", "SGK"],
    "kira": ["TBK"],
}


async def fetch_yargitay_for_domain(domain: str, limit: int) -> list[YargitayDecision]:
    keywords = DOMAIN_KEYWORDS.get(domain, [])
    per_keyword = max(1, limit // max(1, len(keywords)))
    all_decisions: list[YargitayDecision] = []
    seen_ids: set[str] = set()

    async with YargiClient() as client:
        if not await client.health():
            log.warning("yargi_mcp_unreachable", url=client.base_url)
            return []

        for keyword in keywords:
            try:
                items = await client.search_yargitay(keyword, limit=per_keyword)
            except Exception as exc:
                log.error("yargitay_search_failed", keyword=keyword, error=str(exc))
                continue

            for decision in items:
                if decision.id and decision.id not in seen_ids and decision.text:
                    seen_ids.add(decision.id)
                    all_decisions.append(decision)

    log.info("yargitay_total", domain=domain, count=len(all_decisions))
    return all_decisions


async def fetch_mevzuat_for_domain(domain: str) -> list[Madde]:
    kanunlar = DOMAIN_KANUNLAR.get(domain, [])
    all_maddeler: list[Madde] = []

    async with MevzuatClient() as client:
        for kanun_kodu in kanunlar:
            try:
                maddeler = await client.fetch_kanun(kanun_kodu)
                all_maddeler.extend(maddeler)
            except Exception as exc:
                log.error("kanun_fetch_failed", kod=kanun_kodu, error=str(exc))

    log.info("mevzuat_total", domain=domain, count=len(all_maddeler))
    return all_maddeler


def yargitay_to_chunks(decisions: Iterable[YargitayDecision], domain: str) -> list[tuple[str, dict]]:
    """(text, payload) çiftleri — daha sonra embed edilir."""
    pairs: list[tuple[str, dict]] = []
    for decision in decisions:
        for seq, chunk in enumerate(chunk_text(decision.text)):
            chunk_id = f"{decision.id}-c{seq}"
            payload = {
                **decision.to_payload(),
                "chunk_seq": seq,
                "domain": domain,
                "text": chunk,
            }
            pairs.append((chunk, {"id": chunk_id, "payload": payload}))
    return pairs


def mevzuat_to_chunks(maddeler: Iterable[Madde], domain: str) -> list[tuple[str, dict]]:
    pairs: list[tuple[str, dict]] = []
    for madde in maddeler:
        for seq, chunk in enumerate(chunk_mevzuat(madde.metin)):
            chunk_id = f"{madde.id}-c{seq}"
            payload = {
                **madde.to_payload(),
                "chunk_seq": seq,
                "domain": domain,
                "text": chunk.text,
                **chunk.metadata,
            }
            pairs.append((chunk.text, {"id": chunk_id, "payload": payload}))
    return pairs


async def seed_domain(domain: str, limit: int, dry_run: bool) -> int:
    log.info("seed_domain_started", domain=domain, limit=limit)

    decisions = await fetch_yargitay_for_domain(domain, limit)
    maddeler = await fetch_mevzuat_for_domain(domain)

    pairs = yargitay_to_chunks(decisions, domain) + mevzuat_to_chunks(maddeler, domain)
    if not pairs:
        log.warning("no_data_fetched", domain=domain)
        return 0

    log.info("embedding_started", chunk_count=len(pairs))
    embedder = Embedder()
    texts = [text for text, _ in pairs]
    out = embedder.encode(texts, batch_size=12)

    chunks = [
        ChunkPoint(
            id=meta["id"],
            dense_vector=dense,
            sparse_indices=sparse[0],
            sparse_values=sparse[1],
            payload=meta["payload"],
        )
        for (_, meta), dense, sparse in zip(pairs, out.dense, out.sparse)
    ]

    if dry_run:
        log.info("dry_run_completed", domain=domain, would_upsert=len(chunks))
        return len(chunks)

    client = get_client()
    try:
        await ensure_collection(client)
        written = await upsert_chunks(client, chunks)
        total = await count_points(client)
        log.info("seed_domain_completed", domain=domain, written=written, total=total)
        return written
    finally:
        await client.close()


async def seed(domain: Domain, limit: int, dry_run: bool) -> None:
    domains = ["tuketici", "isHukuku", "kira"] if domain == "all" else [domain]
    total = 0
    for d in domains:
        total += await seed_domain(d, limit, dry_run)
    log.info("seed_completed", total_chunks=total, dry_run=dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="ADALET-AGENT veri seeding")
    parser.add_argument(
        "--domain",
        choices=["tuketici", "isHukuku", "kira", "all"],
        default="all",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Domain başına maksimum Yargıtay karar sayısı",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Qdrant'a yazma — sadece fetch + embed et",
    )
    args = parser.parse_args()

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ]
    )

    asyncio.run(seed(args.domain, args.limit, args.dry_run))


if __name__ == "__main__":
    main()
