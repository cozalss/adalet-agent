"""In-process rolling latans metrikleri — P50/P95/P99 görünürlüğü.

"P95/P99 trendi görünmezse kör uçarız." Bu modül dış altyapı (Prometheus/Grafana)
gerektirmeden, son N örneğin yuvarlanan yüzdeliklerini tutar ve `/metrics/latency`
endpoint'i üzerinden okutur.

Kaynak: SSE stream stage timing'leri (first_event_ms, retrieval_done_ms,
first_token_ms, final_ms) + ileride speculative_done/verify_done eklenebilir.

Kapsam/kısıt:
  - Tek-process: her uvicorn worker'ı kendi penceresini tutar (multi-worker'da
    her worker ayrı snapshot verir). Tek-worker dev/prod için yeterli.
  - Bounded deque (default 500 örnek) → bellek sabit, eski örnekler düşer.
  - asyncio tek-thread → kilit gerekmez (record/snapshot atomik sayılır).
"""

from __future__ import annotations

import math
from collections import deque
from threading import Lock
from typing import Any

# Pencere boyutu — son N örnek üzerinden yüzdelik. Sabit bellek.
_WINDOW = 500


class RollingPercentiles:
    """Bir metrik için bounded pencere + yüzdelik snapshot."""

    __slots__ = ("_lock", "_samples")

    def __init__(self, window: int = _WINDOW) -> None:
        self._samples: deque[float] = deque(maxlen=window)
        # threading.Lock — gunicorn sync worker veya thread pool senaryosuna karşı
        # ucuz güvence. asyncio tek-thread'de çekişme yok.
        self._lock = Lock()

    def record(self, value: float | int | None) -> None:
        if value is None:
            return
        with self._lock:
            self._samples.append(float(value))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            vals = sorted(self._samples)
        n = len(vals)
        if n == 0:
            return {"n": 0, "p50": None, "p95": None, "p99": None,
                    "max": None, "avg": None}

        def _pct(p: float) -> float:
            return round(vals[max(0, math.ceil(n * p) - 1)], 1)

        return {
            "n": n,
            "p50": _pct(0.50),
            "p95": _pct(0.95),
            "p99": _pct(0.99),
            "max": round(vals[-1], 1),
            "avg": round(sum(vals) / n, 1),
        }


# --- Modül-seviyesi registry ---
# SSE stream stage'leri + LLM/retrieval darboğaz stage'leri. İsim → RollingPercentiles.
_REGISTRY: dict[str, RollingPercentiles] = {
    # SSE stream stage'leri (stream_timings event'inden)
    "stream.first_event_ms": RollingPercentiles(),
    "stream.retrieval_done_ms": RollingPercentiles(),
    "stream.first_token_ms": RollingPercentiles(),
    "stream.final_ms": RollingPercentiles(),
    # Darboğaz stage'leri — TÜM yollardan (streaming + non-streaming /ask)
    "llm.generation_ms": RollingPercentiles(),    # llama_server_call_done.elapsed_ms
    "retrieval.total_ms": RollingPercentiles(),   # speculative_done.total_ms
    "retrieval.hybrid_ms": RollingPercentiles(),  # speculative_done.hybrid_ms
    "verify.duration_ms": RollingPercentiles(),   # verify_done.elapsed_ms (NLI maliyeti)
    "finalize.duration_ms": RollingPercentiles(), # finalize_done.elapsed_ms
}


def record_stream_timings(timings: dict[str, Any]) -> None:
    """SSE `timing` event payload'unu metriklere kaydet.

    timings = {first_event_ms, retrieval_done_ms, first_token_ms, final_ms}.
    None değerler (kısa-devre yolunda retrieval/draft yok) atlanır.
    """
    _REGISTRY["stream.first_event_ms"].record(timings.get("first_event_ms"))
    _REGISTRY["stream.retrieval_done_ms"].record(timings.get("retrieval_done_ms"))
    _REGISTRY["stream.first_token_ms"].record(timings.get("first_token_ms"))
    _REGISTRY["stream.final_ms"].record(timings.get("final_ms"))


# Tap dispatcher: structlog event adı → (metrik adı, event_dict alanı) eşlemeleri.
# Tek nokta — JSON log'dan geçen her timing event'i otomatik yakalanır
# (streaming /ask/stream + non-streaming /ask + script koşumları dahil).
_EVENT_TAPS: dict[str, list[tuple[str, str]]] = {
    "llama_server_call_done": [("llm.generation_ms", "elapsed_ms")],
    "speculative_done": [("retrieval.total_ms", "total_ms"),
                         ("retrieval.hybrid_ms", "hybrid_ms")],
    "verify_done": [("verify.duration_ms", "elapsed_ms")],
    "finalize_done": [("finalize.duration_ms", "elapsed_ms")],
}


def record_event(event_name: str, event_dict: dict[str, Any]) -> None:
    """structlog tap'inden çağrılır — bilinen timing event'lerini aggregator'a yaz.

    stream_timings ayrı (record_stream_timings ile 4 stage'e dağıtılır).
    Bilinmeyen event/alan sessizce atlanır. ASLA exception fırlatmamalı.
    """
    if event_name == "stream_timings":
        record_stream_timings(event_dict)
        return
    for metric_name, field in _EVENT_TAPS.get(event_name, ()):
        _REGISTRY[metric_name].record(event_dict.get(field))


def snapshot_all() -> dict[str, dict[str, Any]]:
    """Tüm metriklerin yüzdelik snapshot'ı — /metrics/latency için."""
    return {name: m.snapshot() for name, m in _REGISTRY.items()}


def render_prometheus() -> str:
    """Snapshot'ı Prometheus text exposition format'a çevir — GET /metrics için.

    Bağımlılıksız (prometheus_client gerekmez). Önceden hesaplanmış yüzdelikleri
    quantile-etiketli gauge olarak yayar; Prometheus scrape eder, Grafana çizer.
    Self-hosted → veri kutudan çıkmaz (KVKK uyumlu).

    Format:
      adalet_stage_latency_ms{stage="llm.generation_ms",quantile="0.95"} 38802
      adalet_stage_latency_samples{stage="llm.generation_ms"} 2
    """
    lines: list[str] = [
        "# HELP adalet_stage_latency_ms Pipeline stage latans yüzdelikleri (rolling 500).",
        "# TYPE adalet_stage_latency_ms gauge",
    ]
    sample_lines: list[str] = [
        "# HELP adalet_stage_latency_samples Stage başına pencere örnek sayısı.",
        "# TYPE adalet_stage_latency_samples gauge",
    ]
    for name, m in _REGISTRY.items():
        snap = m.snapshot()
        sample_lines.append(f'adalet_stage_latency_samples{{stage="{name}"}} {snap["n"]}')
        if snap["n"] == 0:
            continue
        for q_label, key in (("0.5", "p50"), ("0.95", "p95"), ("0.99", "p99")):
            val = snap[key]
            if val is not None:
                lines.append(
                    f'adalet_stage_latency_ms{{stage="{name}",quantile="{q_label}"}} {val}')
    return "\n".join([*lines, *sample_lines]) + "\n"


def reset_all() -> None:
    """Tüm pencereleri sıfırla (test izolasyonu)."""
    for m in _REGISTRY.values():
        m._samples.clear()
