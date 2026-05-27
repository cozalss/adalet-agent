"""Bulk seed CLI entry point.

Örnekler:
    # Tek domain, tek court — küçük smoke test
    uv run python -m scripts.seed --court yargitay --domain tuketici --limit-per-domain 20

    # Production tam seed (1000 karar × 3 domain × 3 court = ~9000 doc, ~saatler)
    uv run python -m scripts.seed --court all --domain all --limit-per-domain 1000

    # Dry run — embed et ama Qdrant'a yazma
    uv run python -m scripts.seed --domain tuketici --limit-per-domain 10 --dry-run

    # Resume kapalı — state dosyasını yok say
    uv run python -m scripts.seed --no-resume
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Windows: `core.native_preload` pyarrow'u torch'tan ÖNCE yükler — BGE-M3 embedder
# warmup'ı (sentence_transformers→datasets→pyarrow) torch sonrası segfault yapar.
# isort `core`'u `retrieval`'dan önce sıraladığı için preload, Embedder import'undan
# (torch'u çeken) ÖNCE çalışır — sıra KRİTİK, elle bozma.
from core import native_preload  # noqa: F401
from retrieval.embedding import Embedder
from retrieval.vector_store import ensure_collection, get_client
from retrieval.yargi_client import YargiClient

from .config import (
    BEDESTEN_CAPACITY,
    BEDESTEN_REFILL_PER_SEC,
    COURTS,
    DEFAULT_BATCH_CHUNKS,
    DEFAULT_LIMIT_PER_DOMAIN,
    DEFAULT_PROGRESS_EVERY,
    DEFAULT_STATE_DIR,
    DOMAINS,
    SeedConfig,
)
from .metrics import RunStats
from .pipeline import run_pipeline
from .rate_limiter import AsyncTokenBucket
from .sources import build_source
from .state import SeedState

logger = logging.getLogger("scripts.seed")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scripts.seed",
        description=(
            "ADALET-AGENT bulk seed — Türk hukuk veritabanlarından Qdrant'a "
            "resumable, rate-limited indexleme."
        ),
    )
    parser.add_argument(
        "--court",
        choices=["all", *COURTS.keys()],
        default="yargitay",
        help="Hangi mahkemeden çekilsin (varsayılan: yargitay)",
    )
    parser.add_argument(
        "--domain",
        choices=["all", *DOMAINS.keys()],
        default="all",
        help="Hangi hukuk alanı (varsayılan: all)",
    )
    parser.add_argument(
        "--limit-per-domain",
        type=int,
        default=DEFAULT_LIMIT_PER_DOMAIN,
        help=f"Domain başına maks. karar sayısı (varsayılan: {DEFAULT_LIMIT_PER_DOMAIN})",
    )
    parser.add_argument(
        "--batch-chunks",
        type=int,
        default=DEFAULT_BATCH_CHUNKS,
        help=f"Embed batch chunk sayısı (varsayılan: {DEFAULT_BATCH_CHUNKS})",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=DEFAULT_PROGRESS_EVERY,
        help=f"Her N doc'ta progress satırı (varsayılan: {DEFAULT_PROGRESS_EVERY})",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=DEFAULT_STATE_DIR,
        help=f"Progress JSONL dizini (varsayılan: {DEFAULT_STATE_DIR})",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="State dosyasını yok say, baştan başla",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Embed et ama Qdrant'a yazma",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log seviyesi",
    )
    return parser.parse_args(argv)


def _build_config(args: argparse.Namespace) -> SeedConfig:
    courts = list(COURTS.keys()) if args.court == "all" else [args.court]
    domains = list(DOMAINS.keys()) if args.domain == "all" else [args.domain]
    return SeedConfig(
        domains=domains,
        courts=courts,
        limit_per_domain=args.limit_per_domain,
        batch_chunks=args.batch_chunks,
        progress_every=args.progress_every,
        resume=args.resume,
        dry_run=args.dry_run,
        state_dir=args.state_dir,
    )


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


async def _run(cfg: SeedConfig) -> int:
    logger.info("seed_started")
    logger.info(
        "config: courts=%s domains=%s limit=%d batch_chunks=%d dry_run=%s",
        cfg.courts,
        cfg.domains,
        cfg.limit_per_domain,
        cfg.batch_chunks,
        cfg.dry_run,
    )

    logger.info("warming_embedder (BGE-M3 ilk seferde ~2 GB iner, sonra cache'lenir)")
    embedder = Embedder()
    _ = embedder.encode(["sıcak başlatma"], batch_size=1)
    logger.info("embedder_ready")

    rate = AsyncTokenBucket(capacity=BEDESTEN_CAPACITY, refill_per_sec=BEDESTEN_REFILL_PER_SEC)
    qdrant = get_client()
    all_stats: list[RunStats] = []

    try:
        await ensure_collection(qdrant)

        async with YargiClient() as client:
            for court_cfg, domain_cfg in cfg.iter_court_domain_matrix():
                source = build_source(court_cfg.name, client)
                state = SeedState(cfg.state_dir, court_cfg.name, domain_cfg.name)
                if not cfg.resume and state.path.exists():
                    logger.warning("clearing_state %s", state.path)
                    state.path.unlink()

                stats = RunStats(court=court_cfg.name, domain=domain_cfg.name)
                logger.info("=" * 70)
                logger.info("START %s / %s", court_cfg.display_name, domain_cfg.name)
                logger.info("=" * 70)

                try:
                    await run_pipeline(
                        cfg=cfg,
                        source=source,
                        domain_config=domain_cfg,
                        embedder=embedder,
                        qdrant=qdrant,
                        state=state,
                        rate=rate,
                        stats=stats,
                    )
                finally:
                    all_stats.append(stats)
                    logger.info(stats.summary_line())
    finally:
        await qdrant.close()

    logger.info("=" * 70)
    logger.info("ÖZET")
    logger.info("=" * 70)
    total_docs = sum(s.upserted_docs for s in all_stats)
    total_chunks = sum(s.upserted_chunks for s in all_stats)
    total_errors = sum(s.errors for s in all_stats)
    for s in all_stats:
        logger.info("  %s", s.summary_line())
    logger.info("TOPLAM: %d doc, %d chunk, %d hata", total_docs, total_chunks, total_errors)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.log_level)
    cfg = _build_config(args)
    return asyncio.run(_run(cfg))


if __name__ == "__main__":
    sys.exit(main())
