"""core/metrics.py birim testleri — rolling percentile aggregator."""

from __future__ import annotations

import pytest

from core.metrics import (
    RollingPercentiles,
    record_event,
    record_stream_timings,
    render_prometheus,
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
        "llm.generation_ms", "retrieval.total_ms", "retrieval.hybrid_ms",
        "verify.duration_ms", "finalize.duration_ms",
    }


# --- record_event tap dispatcher (structlog tap'inin çağırdığı) ---

def test_record_event_llm_generation():
    record_event("llama_server_call_done", {"elapsed_ms": 9500, "tokens_out": 320})
    assert snapshot_all()["llm.generation_ms"]["n"] == 1
    assert snapshot_all()["llm.generation_ms"]["p50"] == 9500


def test_record_event_speculative_retrieval():
    record_event("speculative_done", {"hybrid_ms": 40, "total_ms": 1800, "strategy": "hyde"})
    snap = snapshot_all()
    assert snap["retrieval.total_ms"]["p50"] == 1800
    assert snap["retrieval.hybrid_ms"]["p50"] == 40


def test_record_event_stream_timings_dispatched():
    record_event("stream_timings", {"first_event_ms": 10, "retrieval_done_ms": 1500,
                                     "first_token_ms": 3000, "final_ms": 12000})
    assert snapshot_all()["stream.final_ms"]["p50"] == 12000


def test_record_event_unknown_ignored():
    record_event("some_random_event", {"foo": 123})
    # Hiçbir metrik etkilenmez
    assert all(s["n"] == 0 for s in snapshot_all().values())


def test_record_event_missing_field_skipped():
    record_event("llama_server_call_done", {"tokens_out": 320})  # elapsed_ms yok
    assert snapshot_all()["llm.generation_ms"]["n"] == 0


def test_metrics_tap_via_structlog():
    """core/logging._metrics_tap: structlog event'i otomatik aggregator'a beslemeli."""
    import structlog

    from core.logging import configure_logging
    configure_logging()
    log = structlog.get_logger()
    log.info("llama_server_call_done", elapsed_ms=8800, tokens_out=300)
    assert snapshot_all()["llm.generation_ms"]["n"] >= 1


def test_record_event_verify_and_finalize():
    record_event("verify_done", {"elapsed_ms": 1200, "verdict": "pass"})
    record_event("finalize_done", {"elapsed_ms": 30, "confidence": 0.7})
    snap = snapshot_all()
    assert snap["verify.duration_ms"]["p50"] == 1200
    assert snap["finalize.duration_ms"]["p50"] == 30


# --- Prometheus exposition format ---

def test_prometheus_empty_has_help_and_samples():
    text = render_prometheus()
    assert "# HELP adalet_stage_latency_ms" in text
    assert "# TYPE adalet_stage_latency_ms gauge" in text
    # boş registry → her stage için samples=0 satırı olmalı
    assert 'adalet_stage_latency_samples{stage="llm.generation_ms"} 0' in text


def test_prometheus_emits_quantiles_after_record():
    record_event("llama_server_call_done", {"elapsed_ms": 9500})
    record_event("llama_server_call_done", {"elapsed_ms": 12000})
    text = render_prometheus()
    assert 'adalet_stage_latency_ms{stage="llm.generation_ms",quantile="0.5"}' in text
    assert 'adalet_stage_latency_ms{stage="llm.generation_ms",quantile="0.95"}' in text
    assert 'adalet_stage_latency_samples{stage="llm.generation_ms"} 2' in text


def test_prometheus_lines_well_formed():
    record_event("verify_done", {"elapsed_ms": 1000})
    text = render_prometheus()
    # Her metrik satırı: ad{etiketler} değer — boşlukla ayrık 2 alan
    for line in text.splitlines():
        if line.startswith("adalet_stage_latency"):
            parts = line.rsplit(" ", 1)
            assert len(parts) == 2
            float(parts[1])  # değer parse edilebilmeli
