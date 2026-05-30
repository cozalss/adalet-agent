"""Uçtan uca latans profili — P50/P95/P99 + stage breakdown.

Tek sorgu ölçümü (N=3) tail latency hakkında hiçbir şey söylemez. Bu harness:
  - N≥30 gerçek sorgu çalıştırır (benchmark'tan)
  - Her sorgu için toplam + node bazlı süre toplar
  - P50/P95/P99 dağılımı raporlar
  - retry tetikleyen sorguları ayrı işaretler (debate retry → 2x retrieval+LLM)

Neden retry kritik: ortalama 11-12s olsa da, debate "retry" veren bir sorgu
mevzuat+emsal+draft+verify'ı tekrar koşar → 22-25s. Bu kuyruğu görmek için
verdict + retry_count başına gruplama yapar.

Çalıştırma:
    LLM_MODE=llamacpp_server uv run python -m scripts.latency_profile --version v1 --n 30
    LLM_MODE=llamacpp_server uv run python -m scripts.latency_profile --n 50 --out eval/runs/latency.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import native_preload  # noqa: F401

logger = logging.getLogger("latency_profile")
logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(0, math.ceil(len(sorted_vals) * p) - 1)
    return sorted_vals[k]


def _load_cases(version: str, n: int) -> list[dict]:
    from scripts.eval_run import _load_benchmark
    cases = _load_benchmark(version)
    # Sorguları çoğalt (n > vaka sayısı ise döngüsel) → daha çok örnek
    out = []
    i = 0
    while len(out) < n:
        out.append(cases[i % len(cases)])
        i += 1
    return out[:n]


async def main(args: argparse.Namespace) -> None:
    from agents.graph import build_graph
    from agents.state import AgentState

    cases = _load_cases(args.version, args.n)
    graph = build_graph()

    # Isınma — ilk sorgu modelleri yükler, ölçüme dahil etme
    print(f"Isınma sorgusu (ölçüm dışı)...", flush=True)
    warmup = AgentState(question="kıdem tazminatı nedir")
    await graph.ainvoke(warmup)

    print(f"Ölçüm başlıyor: {len(cases)} sorgu\n", flush=True)
    samples: list[dict] = []

    for i, case in enumerate(cases, 1):
        q = case["soru"]
        state = AgentState(question=q)
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(graph.ainvoke(state), timeout=90)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            samples.append({
                "id": case.get("id", f"q{i}"),
                "domain": result.get("domain", "?"),
                "verdict": result.get("debate_verdict", "?"),
                "retry_count": result.get("retry_count", 0),
                "total_ms": elapsed_ms,
            })
            tag = ""
            rc = result.get("retry_count", 0)
            if rc:
                tag = f" [RETRY×{rc}]"
            print(f"  [{i:>3}/{len(cases)}] {elapsed_ms:>7.0f}ms  "
                  f"{result.get('domain','?'):<10} {result.get('debate_verdict','?')}{tag}", flush=True)
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            samples.append({"id": case.get("id"), "total_ms": elapsed_ms,
                            "verdict": "TIMEOUT", "retry_count": -1, "domain": "?"})
            print(f"  [{i:>3}/{len(cases)}] TIMEOUT (>{90}s)", flush=True)

    # --- Dağılım — BİMODAL ayrıştır ---
    # Kapsam-dışı/smalltalk sorguları draft/verify atlar → ~1-2ms anında döner.
    # Bunları gerçek hukuki cevaplarla karıştırmak ortalamayı yanıltır.
    SHORT_CIRCUIT_MS = 1000
    legal = sorted(s["total_ms"] for s in samples if s["total_ms"] > SHORT_CIRCUIT_MS)
    short = [s["total_ms"] for s in samples if s["total_ms"] <= SHORT_CIRCUIT_MS]

    totals = sorted(s["total_ms"] for s in samples)
    n = len(totals)

    print("\n" + "=" * 60)
    print(f"  LATANS DAĞILIMI — {n} sorgu (bimodal)")
    print("=" * 60)
    if short:
        print(f"  Kısa-devre (kapsamdışı/smalltalk): {len(short)} sorgu, "
              f"ort {sum(short)/len(short):.0f}ms")
    if legal:
        print(f"\n  GERÇEK HUKUKİ CEVAP: {len(legal)} sorgu  ← kullanıcı deneyimi")
        print(f"    Ortalama:  {sum(legal)/len(legal):>8.0f} ms")
        print(f"    P50:       {_percentile(legal, 0.50):>8.0f} ms")
        print(f"    P90:       {_percentile(legal, 0.90):>8.0f} ms")
        print(f"    P95:       {_percentile(legal, 0.95):>8.0f} ms  ← KUYRUK")
        print(f"    P99:       {_percentile(legal, 0.99):>8.0f} ms")
        print(f"    Min/Max:   {legal[0]:.0f} / {legal[-1]:.0f} ms")

    # --- Retry yolu ayrı ---
    no_retry = [s["total_ms"] for s in samples if s.get("retry_count", 0) == 0]
    with_retry = [s["total_ms"] for s in samples if s.get("retry_count", 0) > 0]
    print(f"\n  Retry YOK ({len(no_retry)} sorgu):  "
          f"ort {sum(no_retry)/len(no_retry):.0f}ms" if no_retry else "  Retry YOK: -")
    if with_retry:
        print(f"  Retry VAR ({len(with_retry)} sorgu): "
              f"ort {sum(with_retry)/len(with_retry):.0f}ms  "
              f"max {max(with_retry):.0f}ms  ← KUYRUK")

    # --- Verdict dağılımı ---
    by_verdict: dict[str, int] = defaultdict(int)
    for s in samples:
        by_verdict[s.get("verdict", "?")] += 1
    print(f"\n  Verdict: {dict(by_verdict)}")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "n": n, "avg_ms": avg,
            "p50": _percentile(totals, 0.50), "p95": _percentile(totals, 0.95),
            "p99": _percentile(totals, 0.99), "max": totals[-1],
            "samples": samples,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  Sonuc -> {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Uçtan uca P95/P99 latans profili")
    parser.add_argument("--version", default="v1", choices=["v1", "v2"])
    parser.add_argument("--n", type=int, default=30, help="Sorgu sayısı (min örneklem)")
    parser.add_argument("--out", default=None, help="JSON çıktı yolu")
    asyncio.run(main(parser.parse_args()))
