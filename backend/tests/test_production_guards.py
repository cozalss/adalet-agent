"""Production fail-fast guard'ları (ECC sweep) — ablation/ölçüm kaldıraçları production'da YASAK.

VERIFY_ENABLED=0 (doğrulama bypass) ve FORCE_RETRY_ONCE=1 (ölçüm hook) ENV=production iken
startup'ı çökertmeli — sessiz misconfig ile sıfır-halüsinasyon garantisinin kalkması imkânsızlaşır.
"""

from __future__ import annotations

import pytest

from main import _log_auth_visibility


def test_verify_disabled_blocked_in_production(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("VERIFY_ENABLED", "0")
    with pytest.raises(RuntimeError, match="VERIFY_ENABLED"):
        _log_auth_visibility()


def test_force_retry_blocked_in_production(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("VERIFY_ENABLED", "1")
    monkeypatch.setenv("FORCE_RETRY_ONCE", "1")
    with pytest.raises(RuntimeError, match="FORCE_RETRY"):
        _log_auth_visibility()


def test_dev_env_allows_ablation(monkeypatch):
    # Lokal dev (ENV!=production): ablation kaldıraçları guard'a takılmaz (yalnız production fail-fast).
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("VERIFY_ENABLED", "0")
    monkeypatch.setenv("FORCE_RETRY_ONCE", "1")
    monkeypatch.setenv("AUTH_ENABLED", "0")
    # Verify/force-retry guard'ı raise ETMEZ; auth da dev'de yalnız uyarı (raise yok).
    _log_auth_visibility()  # exception fırlatmamalı
