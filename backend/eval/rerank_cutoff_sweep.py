"""RERANK_SCORE_MIN cutoff sweep — alakasız-aday eleme eşiği kalibrasyonu (denetim 2026-06-04, #11).

RERANK_SCORE_MIN=0.0 (default) → cross-encoder relevance cutoff KAPALI: zayıf-eşleşen/kapsam-dışı
sorularda bile reranker top-K'yı ZORLA doldurur → alakasız emsal/mevzuat LLM'e + verify'a gürültü
gider (CLAUDE.md §1 'emin değilim' ilkesinin tersi). Bu sweep optimal cutoff'u VERİYE dayalı seçer:
madde_recall@5 DÜŞMEDEN (gerçek maddeyi kaybetmeden) ortalama dönen-aday sayısı (precision proxy)
kaç azalır? sweep_rrf_k.py / verify_calibration.py'ın rerank-eşi.

Çalıştırma (Qdrant + reranker + benchmark gerekli):
    LLM_MODE=llamacpp_server uv run python -m eval.rerank_cutoff_sweep --cutoffs 0.0,0.1,0.2,0.3,0.4

Çıktı: eval/runs/rerank_cutoff_<git_sha>.json — saf _summarize() LLM'siz test edilebilir.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.eval_run import _eval_one, _load_benchmark

RUNS_DIR = Path(__file__).parent / "runs"
DEFAULT_CUTOFFS: tuple[float, ...] = (0.0, 0.1, 0.2, 0.3, 0.4)


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent.parent.parent, stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "no-git"


def _summarize(results: list[dict]) -> dict:
    """Saf agregasyon (LLM'siz test edilebilir). KİLİT metrikler:
    - madde_recall@5: cutoff gerçek maddeyi KAYBETTİRMEMELİ (nötr kalmalı).
    - avg_returned: cutoff alakasız adayı ELEMELİ (düşmesi beklenir = precision artışı).
    """
    n = len(results)
    if not n:
        return {"n": 0}
    madde_cases = [r for r in results if r.get("n_expected_madde")]
    sorted_lat = sorted(r["elapsed_ms"] for r in results)
    return {
        "n": n,
        "n_madde_cases": len(madde_cases),
        # KİLİT-1: gerçek maddeyi kaybetmedik mi (cutoff arttıkça düşmemeli)
        "madde_recall@5": (round(sum(r.get("madde_recall@5", 0.0) for r in madde_cases)
                                 / len(madde_cases), 4) if madde_cases else None),
        # KİLİT-2: ortalama dönen aday (cutoff arttıkça düşer = alakasız eleme = precision proxy)
        "avg_returned": round(sum(len(r.get("got_domains_top5", [])) for r in results) / n, 2),
        "context_precision@5": round(sum(r.get("context_precision@5", 0.0) for r in results) / n, 4),
        "D@1": round(sum(r["domain@1"] for r in results) / n, 4),
        "kanun@5": round(sum(r["kanun@5"] for r in results) / n, 4),
        "MRR": round(sum(r["mrr"] for r in results) / n, 4),
        "avg_latency_ms": round(sum(r["elapsed_ms"] for r in results) / n, 1),
        "p95_latency_ms": round(sorted_lat[int(0.95 * n)] if n > 1 else sorted_lat[0], 1),
    }


async def _run_with_cutoff(cases: list[dict], cutoff: float) -> dict:
    """RERANK_SCORE_MIN module-constant'ını set et (filtre onu okur; reload gerekmez) + rerank koş."""
    import retrieval.reranker as rr
    rr.RERANK_SCORE_MIN = cutoff
    print(f"\n[ RERANK_SCORE_MIN={cutoff} ] başlıyor ({len(cases)} vaka)...")
    results: list[dict] = []
    for i, case in enumerate(cases, 1):
        try:
            r = await _eval_one(case, mode="rerank")
            results.append(r)
            print(f"  [{i:2d}/{len(cases)}] {case['id']} ret={len(r.get('got_domains_top5', []))} "
                  f"({r['elapsed_ms']:.0f}ms)", flush=True)
        except Exception as exc:
            print(f"  [{i:2d}/{len(cases)}] {case['id']} ERROR: {exc}", flush=True)
    return _summarize(results)


def _parse_args(argv: list[str]) -> tuple[list[float], int | None]:
    p = argparse.ArgumentParser(description="RERANK_SCORE_MIN cutoff sweep (rerank mode)")
    p.add_argument("--cutoffs", type=str, default=",".join(str(v) for v in DEFAULT_CUTOFFS),
                   help="Virgülle ayrılmış cutoff değerleri (varsayılan: 0.0,0.1,0.2,0.3,0.4)")
    p.add_argument("--version", default="v2", choices=["v1", "v2"])
    p.add_argument("--limit", type=int, default=None, help="İlk N vaka (debug)")
    a = p.parse_args(argv)
    cutoffs = [float(v.strip()) for v in a.cutoffs.split(",") if v.strip()]
    if not cutoffs:
        raise SystemExit("En az bir cutoff gerekli (--cutoffs 0.2)")
    return cutoffs, a.limit


async def main() -> int:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    cutoffs, limit = _parse_args(sys.argv[1:])
    cases = _load_benchmark("v2")
    if limit:
        cases = cases[:limit]
    print(f"Benchmark: {len(cases)} vaka · cutoff sweep: {cutoffs}")

    metrics: dict[str, dict] = {}
    for c in cutoffs:
        metrics[f"cutoff_{c}"] = await _run_with_cutoff(cases, c)

    sha = _git_sha()
    payload = {
        "git_sha": sha, "timestamp": datetime.now(UTC).isoformat(), "mode": "rerank",
        "n_cases": len(cases), "cutoffs": cutoffs, "metrics": metrics,
        "yorum": "Optimal cutoff: madde_recall@5 düşmeden avg_returned'i en çok azaltan değer.",
    }
    out_path = RUNS_DIR / f"rerank_cutoff_{sha}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'=' * 60}\n  Cutoff sweep tamamlandı: {out_path}\n{'=' * 60}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _preload_models_sync() -> None:
    print("[*] Preload Embedder (sync)...", flush=True)
    from retrieval.embedding import Embedder
    Embedder().encode(["warmup"], return_colbert=False)
    print("[*] Models ready", flush=True)


if __name__ == "__main__":
    _preload_models_sync()
    sys.exit(asyncio.run(main()))
