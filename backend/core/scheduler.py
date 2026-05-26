"""APScheduler factory — periodic data refresh tasks (Sprint-5 W16.4).

FastAPI lifespan'a entegre edilir. Background thread'de çalışır, request'leri
bloklamaz. Job'lar idempotent — aynı saat'te tekrar çalışırsa ek upsert yok
(state tracking ile dedup).

Job listesi:
  - refresh_resmi_gazete (CRON: günlük 03:00 Europe/Istanbul)
  - refresh_yargitay_recent (CRON: haftalık Pazartesi 04:00)

Çalışma modu:
  - Test ortamında: SCHEDULER_ENABLED=0 → factory None döner
  - Production: SCHEDULER_ENABLED=1 (default) → AsyncIOScheduler

NOT: APScheduler import edilir ama job RUN ARTI/MİSAL OLARAK çağrılmaz —
test sırasında scheduler.start() çağrılmaz, sadece factory döner.
"""

from __future__ import annotations

import os

import structlog

log = structlog.get_logger()

SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "1").lower() in {"1", "true", "yes"}
SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "Europe/Istanbul")


def make_scheduler():
    """AsyncIOScheduler factory — APScheduler runtime'ı opsiyonel.

    Returns:
        AsyncIOScheduler instance veya None (SCHEDULER_ENABLED=0).
    """
    if not SCHEDULER_ENABLED:
        log.info("scheduler_disabled")
        return None

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        log.warning("scheduler_apscheduler_missing — pip install apscheduler")
        return None

    scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)

    # --- Resmi Gazete günlük poll (03:00 Türkiye saati) ---
    try:
        from scripts.refresh_resmi_gazete import refresh_once as refresh_rg
        scheduler.add_job(
            refresh_rg,
            trigger=CronTrigger(hour=3, minute=0, timezone=SCHEDULER_TIMEZONE),
            id="refresh_resmi_gazete",
            replace_existing=True,
            misfire_grace_time=3600,  # 1 saat tolere
        )
        log.info("scheduler_job_added", job_id="refresh_resmi_gazete", cron="0 3 * * *")
    except ImportError as exc:
        log.warning("scheduler_rg_skip", error=str(exc))

    # --- Yargıtay son 30 gün delta — haftalık Pazartesi 04:00 ---
    try:
        from scripts.refresh_yargitay_recent import refresh_once as refresh_yg
        scheduler.add_job(
            refresh_yg,
            trigger=CronTrigger(day_of_week="mon", hour=4, minute=0, timezone=SCHEDULER_TIMEZONE),
            id="refresh_yargitay_recent",
            replace_existing=True,
            misfire_grace_time=7200,  # 2 saat tolere
        )
        log.info("scheduler_job_added", job_id="refresh_yargitay_recent", cron="0 4 * * 1")
    except ImportError as exc:
        log.warning("scheduler_yg_skip", error=str(exc))

    return scheduler
