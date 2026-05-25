"""RRF k parametre sweep — Sprint-4 W1.6.

Multi-query expansion'da kullanılan RRF (Reciprocal Rank Fusion) k sabiti
literatürde 60 olarak kabul görüyor. Türkçe hukukta optimum farklı olabilir;
bu script farklı k değerlerini sırayla deneyerek karşılaştırma tablosu üretir.

k formülü: rrf_score = sum(1 / (rank + k))
- Düşük k (40): üst-rank'lara aşırı ağırlık → precision-favored
- Yüksek k (100): rank fark'ları sönümlenir → recall-favored, geç-rank'lara şans

Çalıştırma:
    # llama-server arka planda çalışır olmalı (Qwen 14B Q4 -ngl 20)
    LLM_MODE=llamacpp_server HYDE_ENABLED=0 MULTI_QUERY_ENABLED=1 \\
        uv run python -m eval.sweep_rrf_k --k 40,60,80,100

Çıktı: eval/runs/rrf_sweep_<git_sha>.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.eval_run import _eval_one, _load_benchmark

RUNS_DIR = Path(__file__).parent / "runs"
DEFAULT_K_VALUES: tuple[int, ...] = (40, 60, 80, 100)


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent.parent.parent,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "no-git"


def _summarize(results: list[dict]) -> dict:
    n = len(results)
    if n == 0:
        return {"n": 0}
    sorted_lat = sorted(r["elapsed_ms"] for r in results)
    return {
        "n": n,
        "D@1": round(sum(r["domain@1"] for r in results) / n, 4),
        "D@5": round(sum(r["domain@5"] for r in results) / n, 4),
        "kanun@5": round(sum(r["kanun@5"] for r in results) / n, 4),
        "MRR": round(sum(r["mrr"] for r in results) / n, 4),
        "keyword_recall": round(sum(r["keyword_recall"] for r in results) / n, 4),
        "avg_latency_ms": round(sum(r["elapsed_ms"] for r in results) / n, 1),
        "p95_latency_ms": round(sorted_lat[int(0.95 * n)] if n > 1 else sorted_lat[0], 1),
    }


async def _run_with_k(cases: list[dict], k: int) -> dict:
    """RRF_K env'ini set et + multi_query mode'unu çalıştır.

    NOT: RRF_K module-level olarak okunur; importlib.reload ile yeniden
    yükleriz. Bu sürecin in-memory cache'i (`_query_cache`) korur ama RRF_K
    yeni değeri görür.
    """
    import importlib
    os.environ["RRF_K"] = str(k)
    from retrieval import multi_query
    importlib.reload(multi_query)
    multi_query.reset_cache()   # önceki k ile cache'lenen sorgular geçersiz

    print(f"\n[ RRF_K={k} ] başlıyor ({len(cases)} vaka)...")
    results: list[dict] = []
    for i, case in enumerate(cases, 1):
        try:
            r = await _eval_one(case, mode="multi_query")
            results.append(r)
            mark = "OK" if r["domain@1"] else ("@5" if r["domain@5"] else "MS")
            print(
                f"  [{i:2d}/{len(cases)}] {case['id']} {mark} ({r['elapsed_ms']:.0f}ms)",
                flush=True,
            )
        except Exception as exc:
            print(f"  [{i:2d}/{len(cases)}] {case['id']} ERROR: {exc}", flush=True)
    return _summarize(results)


def _parse_args(argv: list[str]) -> tuple[list[int], int | None]:
    parser = argparse.ArgumentParser(description="RRF k sweep on multi_query mode")
    parser.add_argument(
        "--k",
        type=str,
        default=",".join(str(v) for v in DEFAULT_K_VALUES),
        help="Virgülle ayrılmış k değerleri (varsayılan: 40,60,80,100)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Sadece ilk N vakayı çalıştır (debug için)",
    )
    args = parser.parse_args(argv)
    k_values = [int(v.strip()) for v in args.k.split(",") if v.strip()]
    if not k_values:
        raise SystemExit("En az bir k değeri gerekli (--k 60)")
    return k_values, args.limit


async def main() -> int:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    k_values, limit = _parse_args(sys.argv[1:])
    cases = _load_benchmark()
    if limit:
        cases = cases[:limit]
    print(f"Benchmark: {len(cases)} vaka")
    print(f"k sweep: {k_values}")

    metrics: dict[str, dict] = {}
    for k in k_values:
        metrics[f"rrf_k_{k}"] = await _run_with_k(cases, k)

    sha = _git_sha()
    payload = {
        "git_sha": sha,
        "timestamp": datetime.now(UTC).isoformat(),
        "mode": "multi_query",
        "benchmark": "data/eval_benchmark/benchmark.jsonl",
        "n_cases": len(cases),
        "k_values": k_values,
        "metrics": metrics,
    }

    out_path = RUNS_DIR / f"rrf_sweep_{sha}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'=' * 60}")
    print(f"  RRF sweep tamamlandı: {out_path}")
    print(f"{'=' * 60}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _preload_models_sync() -> None:
    """Lifespan-preload pattern — main thread'de sync warmup."""
    print("[*] Preload Embedder (sync)...", flush=True)
    from retrieval.embedding import Embedder
    Embedder().encode(["warmup"], return_colbert=False)
    print("[*] Models ready", flush=True)


if __name__ == "__main__":
    _preload_models_sync()
    sys.exit(asyncio.run(main()))
