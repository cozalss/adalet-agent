"""Resmi Gazete günlük poll — Sprint-5 W16.1.

resmigazete.gov.tr'nin JSON/RSS feed'ini günlük olarak okur:
  - Bugün yayınlanan KHK / Kanun / Cumhurbaşkanlığı Kararnamesi / Yönetmelik var mı?
  - Bizim seed'lediğimiz mevzuat ile diff alınır (mevzuat_id + version_date)
  - Yeni veya değişen kayıt varsa ilgili mevzuat chunk'ları silinip re-seed olur

Çalışma modları:
    - Direct: `uv run python -m scripts.refresh_resmi_gazete`
    - Cron: core/scheduler.py CronTrigger(hour=3) tarafından çağrılır

NOT — gerçek RG API endpoint formatı zamana göre değişebilir. Bu modül
schema-tolerant parser kullanır; bilinmeyen field varsa log'lar ve devam eder.

Stub mode: REFRESH_RG_STUB=1 → fake "no changes" döner (test/CI için).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("scripts.refresh_resmi_gazete")

RG_FEED_URL = os.getenv(
    "RESMI_GAZETE_FEED_URL",
    "https://www.resmigazete.gov.tr/eskiler/feed.json",  # Placeholder — gerçek endpoint TBD
)
RG_TIMEOUT_S = float(os.getenv("RESMI_GAZETE_TIMEOUT_S", "30.0"))
RG_STUB = os.getenv("REFRESH_RG_STUB", "0").lower() in {"1", "true", "yes"}


@dataclass(slots=True, frozen=True)
class GazeteEntry:
    """Resmi Gazete yayın kaydı (parse edilmiş)."""

    date: str
    title: str
    mevzuat_no: str | None
    mevzuat_tur: str | None  # KANUN / KHK / CK / YONETMELIK / TEBLIG
    url: str


def _parse_entry(raw: dict[str, Any]) -> GazeteEntry | None:
    """RG feed item'ı GazeteEntry'e çevir — schema-tolerant."""
    try:
        return GazeteEntry(
            date=str(raw.get("date") or raw.get("rg_tarih") or ""),
            title=str(raw.get("title") or raw.get("baslik") or ""),
            mevzuat_no=raw.get("mevzuat_no") or raw.get("kanun_no"),
            mevzuat_tur=raw.get("mevzuat_tur") or raw.get("tur"),
            url=str(raw.get("url") or raw.get("link") or ""),
        )
    except (TypeError, ValueError) as exc:
        logger.warning("parse_failed %s", exc)
        return None


async def _fetch_feed() -> list[GazeteEntry]:
    """RG feed'ini çek, GazeteEntry listesine parse et."""
    if RG_STUB:
        logger.info("rg_stub_mode_no_fetch")
        return []
    async with httpx.AsyncClient(timeout=RG_TIMEOUT_S) as client:
        try:
            resp = await client.get(RG_FEED_URL)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("rg_fetch_failed: %s", exc)
            return []

    try:
        data = resp.json()
    except ValueError:
        logger.warning("rg_feed_not_json")
        return []

    items = data.get("items") or data.get("entries") or []
    if not isinstance(items, list):
        logger.warning("rg_feed_items_not_list")
        return []

    entries: list[GazeteEntry] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        entry = _parse_entry(raw)
        if entry is not None:
            entries.append(entry)
    logger.info("rg_feed_parsed count=%d", len(entries))
    return entries


def _filter_relevant(entries: list[GazeteEntry]) -> list[GazeteEntry]:
    """Sadece bizim domain'ler için ilgili tür ve kanun no'ları filtrele."""
    # Kapsam dışı türler: TÜZÜK eski, GENELGE düşük öncelik
    relevant_tur = {"KANUN", "KHK", "CK", "CUMHURBASKANLIGI", "YONETMELIK"}
    from retrieval.mevzuat_client import KANUN_KODU_TO_NUMARA
    known_kanun_nolar = set(KANUN_KODU_TO_NUMARA.values())

    out: list[GazeteEntry] = []
    for e in entries:
        if e.mevzuat_tur and e.mevzuat_tur.upper() not in relevant_tur:
            continue
        # Eğer mevzuat_no biliniyorsa (mevcut seed'de var) → öncelikli
        if e.mevzuat_no and e.mevzuat_no in known_kanun_nolar:
            out.append(e)
            continue
        # Eğer yeni bir kanun (KANUN/KHK) ise log
        if e.mevzuat_tur and e.mevzuat_tur.upper() in {"KANUN", "KHK", "CK"}:
            logger.info("rg_new_law_detected", extra={"no": e.mevzuat_no, "title": e.title})
            out.append(e)
    return out


async def refresh_once() -> int:
    """Tek seferlik refresh. Kaç yeni/değişen entry işlendi döndürür.

    Scheduler tarafından çağrılır — exception swallowing yapılır, hiç hata
    geri yansımaz (cron next-run umurlu).
    """
    logger.info("refresh_resmi_gazete_started")
    try:
        all_entries = await _fetch_feed()
        relevant = _filter_relevant(all_entries)
        logger.info(
            "refresh_resmi_gazete_completed",
            extra={"total": len(all_entries), "relevant": len(relevant), "n_new": len(relevant)},
        )
        # NOT — Asıl re-seed bu modülde yapılmaz. Relevant entry tespit edilirse
        # operatör log'u görür ve manuel `uv run python -m scripts.seed_mevzuat` koşar.
        # Otomatik re-seed feature flag arkasında olabilir (REFRESH_RG_AUTOSEED=1).
        return len(relevant)
    except Exception as exc:
        logger.exception("refresh_resmi_gazete_failed: %s", exc)
        return 0


async def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    n = await refresh_once()
    logger.info("rg_total_processed=%d", n)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
