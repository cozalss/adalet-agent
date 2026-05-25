"""Baseline donduran — eval_run.py'ı 2 modda çalıştır, JSON'a yaz.

Amaç: Her iyileştirmeyi (HyDE, Citation Verifier, LangGraph) bu sabit
referansa göre delta olarak raporlamak. TDD jürisi için "şeffaf eval".

Çalıştırma:
    uv run python -m eval.freeze_baseline

Çıktı:
    eval/runs/v0_baseline_<git_sha>.json
    {
      "git_sha": "...",
      "timestamp": "...",
      "models": {
        "embedder": "BAAI/bge-m3",
        "reranker": "BAAI/bge-reranker-v2-m3"
      },
      "hybrid":         {"D@1": 0.28, ...},
      "hybrid+rerank":  {"D@1": 0.38, ...}
    }
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# Mevcut eval scriptini in-process çağıracağız ki bağımlılık aynı kalsın
sys.path.insert(0, str(Path(__file__).parent.parent))
import asyncio

from scripts.eval_run import _eval_one, _load_benchmark

RUNS_DIR = Path(__file__).parent / "runs"


def _git_sha() -> str:
    """Mevcut HEAD SHA — eval'i reproduce etmek için."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent.parent.parent,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "no-git"


def _percentile(values: list[float], p: float) -> float:
    """Sıralı listeden p-percentile (linear interpolation yok, en yakın indeks)."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(int(p * len(s)), len(s) - 1)
    return s[idx]


def _summarize(results: list[dict]) -> dict:
    n = len(results)
    if n == 0:
        return {"n": 0}
    latencies = [r["elapsed_ms"] for r in results]
    # Sprint-4 W2.3: context_precision@5 + p50/p95/p99 latency breakdown.
    # context_precision@5 — Ragas-style top-K relevance: top-5 sonuçların kaçı
    # expected_domain'e uyumlu. domain@5 binary'den daha granular sinyal.
    return {
        "n": n,
        "D@1": round(sum(r["domain@1"] for r in results) / n, 4),
        "D@5": round(sum(r["domain@5"] for r in results) / n, 4),
        "kanun@5": round(sum(r["kanun@5"] for r in results) / n, 4),
        "MRR": round(sum(r["mrr"] for r in results) / n, 4),
        "keyword_recall": round(sum(r["keyword_recall"] for r in results) / n, 4),
        "context_precision@5": round(
            sum(r.get("context_precision@5", 0.0) for r in results) / n, 4,
        ),
        "avg_latency_ms": round(sum(latencies) / n, 1),
        "p50_latency_ms": round(_percentile(latencies, 0.50), 1),
        "p95_latency_ms": round(_percentile(latencies, 0.95), 1),
        "p99_latency_ms": round(_percentile(latencies, 0.99), 1),
    }


async def _run_mode(cases: list[dict], mode: str, label: str) -> dict:
    print(f"\n[ {label} ] başlıyor ({len(cases)} vaka)...")
    results: list[dict] = []
    for i, case in enumerate(cases, 1):
        try:
            r = await _eval_one(case, mode=mode)
            results.append(r)
            mark = "OK" if r["domain@1"] else ("@5" if r["domain@5"] else "MS")
            print(f"  [{i:2d}/{len(cases)}] {case['id']} {mark} ({r['elapsed_ms']:.0f}ms)",
                  flush=True)
        except Exception as exc:
            print(f"  [{i:2d}/{len(cases)}] {case['id']} ERROR: {exc}", flush=True)
    return _summarize(results)


def _parse_args(argv: list[str]) -> tuple[list[str], str]:
    """CLI: `--modes hybrid,rerank,hyde,multi_query` + `--benchmark v1|v2`.

    Default modes: 4 mode (hybrid + rerank + hyde + multi_query).
    Default benchmark: v1 (50 vaka, eski). v2 = Sprint-4 W2 expansion (186 vaka).
    """
    valid_modes = {"hybrid", "rerank", "hyde", "multi_query"}
    default_modes = ["hybrid", "rerank", "hyde", "multi_query"]
    modes = default_modes
    benchmark_version = "v1"

    for i, a in enumerate(argv):
        if a == "--modes" and i + 1 < len(argv):
            sel = [m.strip() for m in argv[i + 1].split(",") if m.strip()]
            invalid = [m for m in sel if m not in valid_modes]
            if invalid:
                raise SystemExit(
                    f"Bilinmeyen mode(lar): {invalid}; geçerli: {valid_modes}",
                )
            modes = sel
        elif a == "--benchmark" and i + 1 < len(argv):
            ver = argv[i + 1].strip().lower()
            if ver not in {"v1", "v2"}:
                raise SystemExit(f"Bilinmeyen --benchmark: {ver}; v1|v2")
            benchmark_version = ver
    return modes, benchmark_version


async def main() -> int:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    modes, benchmark_version = _parse_args(sys.argv[1:])
    cases = _load_benchmark(version=benchmark_version)
    print(f"Benchmark: {len(cases)} vaka (version={benchmark_version})")
    print(f"Modes: {', '.join(modes)}")

    mode_labels = {
        "hybrid": "HYBRID",
        "rerank": "HYBRID+RERANK",
        "hyde": "HYBRID+HYDE",
        "multi_query": "HYBRID+MULTI_QUERY",
    }
    metrics: dict[str, dict] = {}
    for mode in modes:
        label = mode_labels[mode]
        metrics[mode] = await _run_mode(cases, mode=mode, label=label)

    sha = _git_sha()
    benchmark_path = (
        "data/eval_benchmark/benchmark_v2.jsonl"
        if benchmark_version == "v2"
        else "data/eval_benchmark/benchmark.jsonl"
    )
    payload = {
        "git_sha": sha,
        "timestamp": datetime.now(UTC).isoformat(),
        "benchmark": benchmark_path,
        "benchmark_version": benchmark_version,
        "n_cases": len(cases),
        "models": {
            "embedder": "BAAI/bge-m3",
            "reranker": "BAAI/bge-reranker-v2-m3",
            "nli_verifier": "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
        },
        # Geriye uyumlu key'ler — eski script'ler "hybrid" / "hybrid+rerank" bekler
        "hybrid": metrics.get("hybrid", {}),
        "hybrid+rerank": metrics.get("rerank", {}),
    }
    if "hyde" in metrics:
        payload["hybrid+hyde"] = metrics["hyde"]
    if "multi_query" in metrics:
        payload["hybrid+multi_query"] = metrics["multi_query"]

    # Versiyon suffix: v2 benchmark / hyde-mq / baseline ayrımı dosya adında.
    if benchmark_version == "v2":
        suffix = "v2_w2"   # Sprint-4 W2 baseline
    elif "hyde" in metrics or "multi_query" in metrics:
        suffix = "v1_hyde"
    else:
        suffix = "v0_baseline"
    out_path = RUNS_DIR / f"{suffix}_{sha}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"  Baseline donduruldu: {out_path}")
    print(f"{'=' * 60}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _preload_models_sync() -> None:
    """Lifespan-preload pattern: Windows + asyncio + torch CPU lazy load
    kombinasyonu segfault (exit 139) yapıyor. asyncio.run() çağrısından ÖNCE
    main thread'de sync warmup yap — main.py:lifespan ile aynı mantık.
    """
    print("[*] Preload Embedder (sync, main thread)...", flush=True)
    from retrieval.embedding import Embedder
    Embedder().encode(["warmup"], return_colbert=False)
    print("[*] Preload Reranker...", flush=True)
    from retrieval.reranker import get_reranker
    _ = get_reranker()._model
    print("[*] Models ready", flush=True)


if __name__ == "__main__":
    _preload_models_sync()
    sys.exit(asyncio.run(main()))
