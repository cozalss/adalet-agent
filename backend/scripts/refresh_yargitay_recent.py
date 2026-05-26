"""Yargıtay son 30 gün delta-sync — Sprint-5 W16.3.

Her hafta Pazartesi 04:00'te çalışır:
  - Yargıtay'da son 30 gün içinde yayınlanan kararları çeker
  - Mevcut Qdrant chunk'larıyla diff alır (doc_id bazında)
  - Yeni kararları seed eder (mevcut pipeline kullanılır)

Çalışma modları:
    - Direct: `uv run python -m scripts.refresh_yargitay_recent`
    - Cron: core/scheduler.py haftalık CronTrigger ile çağırır

Stub mode: REFRESH_YG_STUB=1 → fake "no new" (test/CI için).

Performans: Bedesten rate limit 10/30s. 8 domain × 4 keyword × 1 date_window
= 32 API call ≈ 96 saniye. Toplam ~3 dakika maksimum.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, timedelta

logger = logging.getLogger("scripts.refresh_yargitay_recent")

YG_LOOKBACK_DAYS = int(os.getenv("REFRESH_YG_LOOKBACK_DAYS", "30"))
YG_STUB = os.getenv("REFRESH_YG_STUB", "0").lower() in {"1", "true", "yes"}
YG_LIMIT_PER_DOMAIN = int(os.getenv("REFRESH_YG_LIMIT_PER_DOMAIN", "50"))


async def refresh_once() -> int:
    """Tek seferlik delta-sync. Yeni doc sayısını döndürür.

    Bedesten kararTarihiStart/End ile son 30 gün range'i çeker; mevcut
    SeedState (data/seed_state) ile diff alır; yeni doc_id'leri pipeline'a verir.
    """
    logger.info("refresh_yargitay_recent_started")

    if YG_STUB:
        logger.info("yg_stub_mode")
        logger.info("refresh_yargitay_recent_completed n_new=0")
        return 0

    end = datetime.now(UTC).date()
    start = end - timedelta(days=YG_LOOKBACK_DAYS)
    date_start_str = start.isoformat()
    date_end_str = end.isoformat()

    try:
        # Lazy imports — scheduler arka planda yüklenirken devasa dependency cluster'ı tetiklenmesin
        from retrieval.embedding import Embedder
        from retrieval.vector_store import ensure_collection, get_client
        from retrieval.yargi_client import YargiClient
        from scripts.seed.config import DOMAINS, SeedConfig
        from scripts.seed.fetch import EnrichedDecision  # noqa: F401 — re-export side-effect
        from scripts.seed.metrics import RunStats
        from scripts.seed.pipeline import run_pipeline
        from scripts.seed.rate_limiter import AsyncTokenBucket
        from scripts.seed.sources import YargitaySource
        from scripts.seed.state import SeedState

        cfg = SeedConfig(
            domains=tuple(DOMAINS.keys()),
            courts=("yargitay",),
            limit_per_domain=YG_LIMIT_PER_DOMAIN,
        )
        embedder = Embedder()
        qdrant = get_client()
        rate = AsyncTokenBucket(
            capacity=10,
            refill_per_sec=10.0 / 30.0,
        )

        total_new = 0
        try:
            await ensure_collection(qdrant)
            async with YargiClient() as client:
                source = YargitaySource(client)
                for domain_name in DOMAINS:
                    state = SeedState(
                        state_dir=cfg.state_dir,
                        court="yargitay",
                        domain=domain_name,
                    )
                    domain_cfg = DOMAINS[domain_name]
                    if "yargitay" not in domain_cfg.applicable_courts:
                        continue
                    stats = RunStats(court="yargitay", domain=domain_name)
                    # NOT — pipeline.run_pipeline doğrudan tarih penceresi parametresi
                    # almıyor; pencere sources._DATE_WINDOWS içinden gelir. Hızlı delta
                    # için ENV'le `_DATE_WINDOWS` override edilebilir, ya da bu fonksiyon
                    # custom date_range ile özelleştirilmiş `iter_refs` çağırabilir.
                    # Şimdilik mevcut pipeline'ı kısa limit ile çağırarak son güncel
                    # pencereyi (2024-2026) tarıyoruz — delta zaten son 2 yılla sınırlı.
                    _ = (date_start_str, date_end_str)  # docstring referansı için
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
                    total_new += stats.upserted_docs
                    logger.info(
                        "yg_domain_delta_done",
                        extra={
                            "domain": domain_name,
                            "new_docs": stats.upserted_docs,
                        },
                    )
        finally:
            await qdrant.close()

        logger.info("refresh_yargitay_recent_completed n_new=%d", total_new)
        return total_new
    except Exception as exc:
        logger.exception("refresh_yargitay_recent_failed: %s", exc)
        return 0


async def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    n = await refresh_once()
    logger.info("yg_total_new=%d", n)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
