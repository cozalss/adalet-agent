"""core/metrics.py birim testleri — rolling percentile aggregator."""

from __future__ import annotations

import pytest

from core.metrics import (
    RollingPercentiles,
    record_stream_timings,
    reset_all,
    snapshot_all,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_all()
    yield
    reset_all()


# --- RollingPercentiles ---

def test_empty_snapshot_is_none():
    rp = RollingPercentiles()
    snap = rp.snapshot()
    assert snap["n"] == 0
    assert snap["p95"] is None


def test_single_value():
    rp = RollingPercentiles()
    rp.record(100)
    snap = rp.snapshot()
    assert snap["n"] == 1
    assert snap["p50"] == 100
    assert snap["p95"] == 100
    assert snap["max"] == 100


def test_percentiles_on_known_distribution():
    rp = RollingPercentiles()
    for v in range(1, 101):  # 1..100
        rp.record(v)
    snap = rp.snapshot()
    assert snap["n"] == 100
    assert snap["p50"] == 50
    assert snap["p95"] == 95
    assert snap["p99"] == 99
    assert snap["max"] == 100
    assert snap["avg"] == 50.5


def test_none_value_ignored():
    rp = RollingPercentiles()
    rp.record(None)
    rp.record(50)
    assert rp.snapshot()["n"] == 1


def test_bounded_window_drops_old():
    rp = RollingPercentiles(window=10)
    for v in range(100):  # 100 örnek ama pencere 10
        rp.record(v)
    snap = rp.snapshot()
    assert snap["n"] == 10
    # Son 10 örnek: 90..99
    assert snap["max"] == 99
    assert snap["p50"] == 94  # ceil(10*0.5)-1 = 4 → vals[4] = 94


# --- record_stream_timings + snapshot_all ---

def test_record_stream_timings_routes_to_stages():
    record_stream_timings({
        "first_event_ms": 10,
        "retrieval_done_ms": 1500,
        "first_token_ms": 3000,
        "final_ms": 12000,
    })
    snap = snapshot_all()
    assert snap["stream.first_event_ms"]["n"] == 1
    assert snap["stream.final_ms"]["p50"] == 12000


def test_record_stream_timings_skips_none_stages():
    # Kısa-devre yolu: retrieval/draft yok (None)
    record_stream_timings({
        "first_event_ms": 5,
        "retrieval_done_ms": None,
        "first_token_ms": None,
        "final_ms": 8,
    })
    snap = snapshot_all()
    assert snap["stream.first_event_ms"]["n"] == 1
    assert snap["stream.retrieval_done_ms"]["n"] == 0  # None atlandı
    assert snap["stream.final_ms"]["n"] == 1


def test_snapshot_all_has_all_stages():
    snap = snapshot_all()
    assert set(snap) == {
        "stream.first_event_ms", "stream.retrieval_done_ms",
        "stream.first_token_ms", "stream.final_ms",
    }
