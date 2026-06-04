"""Tam RAG baseline ölçümü — 186-vaka benchmark, domain-bazlı madde_recall@5 (denetim 2026-06-04).

'Sistemimiz ne durumda' sorusunun GERÇEK, ölçülmüş cevabı. .env (mursit_hybrid + Mursit + sparse)
+ native_preload (BGE-M3 import-sırası crash fix) ile kurulur. LLM GEREKMEZ (hybrid/rerank mode).

Çalıştır:  cd backend && uv run python -m scripts.run_baseline --mode rerank
Çıktı: konsol özeti (domain-bazlı) + eval/runs/baseline_<mode>_<sha>.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import core.native_preload  # noqa: F401  BGE-M3 import-sırası crash fix (bu kutuda gerekli)
from scripts.eval_run import _eval_one, _load_benchmark


def _git_sha() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                      cwd=Path(__file__).parent.parent.parent,
                                      stderr=subprocess.DEVNULL)
        return out.decode().strip()
    except Exception:
        return "no-git"


def _avg(rows: list[dict], key: str) -> float:
    return round(sum(r.get(key, 0.0) for r in rows) / len(rows), 4) if rows else 0.0


def _madde_recall(rows: list[dict]) -> float | None:
    md = [r for r in rows if r.get("n_expected_madde")]
    return _avg(md, "madde_recall@5") if md else None


def _summary(rows: list[dict]) -> dict:
    return {
        "n": len(rows),
        "domain@1": _avg(rows, "domain@1"),
        "domain@5": _avg(rows, "domain@5"),
        "kanun@5": _avg(rows, "kanun@5"),
        "MRR": _avg(rows, "mrr"),
        "madde_recall@5": _madde_recall(rows),
        "madde_mrr": _avg([r for r in rows if r.get("n_expected_madde")], "madde_mrr"),
        "context_precision@5": _avg(rows, "context_precision@5"),
        "keyword_recall": _avg(rows, "keyword_recall"),
    }


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="rerank", choices=["hybrid", "rerank", "hyde", "multi_query"])
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    cases = _load_benchmark("v2")
    if args.limit:
        cases = cases[:args.limit]
    print(f"Baseline: {len(cases)} vaka · mode={args.mode} · koleksiyon=mursit_hybrid (LLM yok)\n", flush=True)

    rows: list[dict] = []
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for i, c in enumerate(cases, 1):
        try:
            r = await _eval_one(c, mode=args.mode)
            rows.append(r)
            by_domain[c["expected_domain"]].append(r)
            if i % 20 == 0:
                print(f"  ...{i}/{len(cases)}", flush=True)
        except Exception as exc:
            print(f"  [{i}] {c['id']} ERROR: {exc}", flush=True)

    overall = _summary(rows)
    per_domain = {d: _summary(rs) for d, rs in sorted(by_domain.items())}

    bar = "=" * 72
    print(f"\n{bar}\n  RAG BASELINE — {args.mode} — {len(rows)} vaka\n{bar}")
    print(f"  GENEL: domain@1={overall['domain@1']:.0%} · kanun@5={overall['kanun@5']:.0%} · "
          f"MRR={overall['MRR']:.3f} · **madde_recall@5={overall['madde_recall@5']}** · "
          f"madde_mrr={overall['madde_mrr']:.3f}")
    print(f"  {'-' * 70}")
    print(f"  {'domain':12s} {'n':>3s} {'dom@1':>6s} {'kanun@5':>8s} {'madde_R@5':>10s} {'madde_MRR':>10s}")
    for d, s in per_domain.items():
        mr = s["madde_recall@5"]
        print(f"  {d:12s} {s['n']:>3d} {s['domain@1']:>6.0%} {s['kanun@5']:>8.0%} "
              f"{(f'{mr:.0%}' if mr is not None else '-'):>10s} {s['madde_mrr']:>10.3f}")
    print(bar)

    sha = _git_sha()
    out = Path(__file__).parent.parent / "eval" / "runs" / f"baseline_{args.mode}_{sha}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "git_sha": sha, "timestamp": datetime.now(UTC).isoformat(), "mode": args.mode,
        "n": len(rows), "overall": overall, "per_domain": per_domain,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
