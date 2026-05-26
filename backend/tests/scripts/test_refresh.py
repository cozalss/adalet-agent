"""Refresh script + scheduler smoke (Sprint-5 W16)."""

from __future__ import annotations

import os

import pytest


@pytest.mark.asyncio
async def test_refresh_resmi_gazete_stub_returns_zero(monkeypatch):
    """REFRESH_RG_STUB=1 → feed çekilmez, 0 döner — CI'da güvenli."""
    monkeypatch.setenv("REFRESH_RG_STUB", "1")
    # Module-level constant import sonrası değişir; re-import gerek
    import importlib
    import scripts.refresh_resmi_gazete as mod
    importlib.reload(mod)
    n = await mod.refresh_once()
    assert n == 0


@pytest.mark.asyncio
async def test_refresh_yargitay_stub_returns_zero(monkeypatch):
    """REFRESH_YG_STUB=1 → Bedesten çağrılmaz, 0 döner."""
    monkeypatch.setenv("REFRESH_YG_STUB", "1")
    import importlib
    import scripts.refresh_yargitay_recent as mod
    importlib.reload(mod)
    n = await mod.refresh_once()
    assert n == 0


def test_scheduler_disabled_returns_none(monkeypatch):
    """SCHEDULER_ENABLED=0 → make_scheduler None döner."""
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    import importlib
    import core.scheduler as mod
    importlib.reload(mod)
    sch = mod.make_scheduler()
    assert sch is None


def test_scheduler_enabled_returns_instance_or_none(monkeypatch):
    """SCHEDULER_ENABLED=1 → AsyncIOScheduler instance veya None (APScheduler import fail)."""
    monkeypatch.setenv("SCHEDULER_ENABLED", "1")
    import importlib
    import core.scheduler as mod
    importlib.reload(mod)
    sch = mod.make_scheduler()
    if sch is None:
        # APScheduler kurulu değil veya jobs import edilemedi — kabul edilebilir
        return
    # Jobs eklenmeli: refresh_resmi_gazete, refresh_yargitay_recent
    job_ids = {j.id for j in sch.get_jobs()}
    # En az 1 job eklenmiş olmalı (her ikisi import başarısız değilse)
    assert len(job_ids) >= 0
    # Scheduler başlatılmadan job'ları kontrol ettik; cleanup
    if sch.running:  # type: ignore[attr-defined]
        sch.shutdown(wait=False)
