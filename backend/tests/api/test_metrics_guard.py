"""/metrics + /metrics/latency opsiyonel METRICS_TOKEN guard (denetim 2026-06-04).

Bulgu 13: bu endpoint'ler iç timing-metriklerini auth'suz/rate-limit'siz açıyordu.
Env-gated guard: METRICS_TOKEN ayarlıysa token zorunlu; değilse davranış değişmez
(private-net Prometheus scrape bozulmaz). Defense-in-depth.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(autouse=True)
def _isolate_auth(monkeypatch):
    # /metrics global auth middleware'ine takılmasın — yalnız token-guard'ı test et.
    monkeypatch.setenv("AUTH_ENABLED", "0")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_metrics_open_without_token_env(monkeypatch, client):
    """METRICS_TOKEN ayarlı DEĞİLSE → 200 (mevcut davranış korunur)."""
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    assert client.get("/metrics/latency").status_code == 200
    assert client.get("/metrics").status_code == 200


def test_metrics_requires_token_when_env_set(monkeypatch, client):
    """METRICS_TOKEN ayarlıysa → token'sız 401; doğru token (Bearer / X-Metrics-Token) → 200."""
    monkeypatch.setenv("METRICS_TOKEN", "s3cret-token")
    assert client.get("/metrics/latency").status_code == 401
    assert client.get("/metrics").status_code == 401
    assert client.get(
        "/metrics/latency", headers={"Authorization": "Bearer s3cret-token"},
    ).status_code == 200
    assert client.get(
        "/metrics", headers={"X-Metrics-Token": "s3cret-token"},
    ).status_code == 200


def test_metrics_wrong_token_rejected(monkeypatch, client):
    monkeypatch.setenv("METRICS_TOKEN", "s3cret-token")
    assert client.get(
        "/metrics", headers={"Authorization": "Bearer yanlis"},
    ).status_code == 401
