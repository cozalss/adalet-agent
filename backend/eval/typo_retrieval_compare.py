"""Compare clean vs typo retrieval metrics with typo tolerance on/off.

Uses scripts.eval_run._eval_one so the metrics stay aligned with the main
retrieval benchmark runner, but keeps stdout/stderr quiet and writes compact
JSON summaries.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from core import native_preload  # noqa: F401
from scripts.eval_run import _eval_one, _load_benchmark


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(p * len(ordered)), len(ordered) - 1)
    return float(ordered[idx])


def _summarize(rows: list[dict[str, Any]], errors: list[dict[str, str]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0, "errors": len(errors)}
    latencies = [float(r["elapsed_ms"]) for r in rows]
    madde_cases = [r for r in rows if r.get("n_expected_madde")]
    out: dict[str, Any] = {
        "n": n,
        "errors": len(errors),
        "domain@1": round(sum(bool(r["domain@1"]) for r in rows) / n, 4),
        "domain@5": round(sum(bool(r["domain@5"]) for r in rows) / n, 4),
        "kanun@5": round(sum(bool(r["kanun@5"]) for r in rows) / n, 4),
        "kanun@8": round(sum(bool(r.get("kanun@8")) for r in rows) / n, 4),
        "mrr": round(sum(float(r["mrr"]) for r in rows) / n, 4),
        "keyword_recall": round(sum(float(r["keyword_recall"]) for r in rows) / n, 4),
        "context_precision@5": round(
            sum(float(r.get("context_precision@5", 0.0)) for r in rows) / n,
            4,
        ),
        "avg_latency_ms": round(sum(latencies) / n, 1),
        "p50_latency_ms": round(_percentile(latencies, 0.50), 1),
        "p95_latency_ms": round(_percentile(latencies, 0.95), 1),
    }
    if madde_cases:
        m = len(madde_cases)
        out["madde_cases"] = m
        out["madde_recall@5"] = round(
            sum(float(r.get("madde_recall@5", 0.0)) for r in madde_cases) / m,
            4,
        )
        out["madde_recall@8"] = round(
            sum(float(r.get("madde_recall@8", 0.0)) for r in madde_cases) / m,
            4,
        )
        out["madde_mrr"] = round(
            sum(float(r.get("madde_mrr", 0.0)) for r in madde_cases) / m,
            4,
        )

    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_domain[str(row["expected_domain"])].append(row)
    out["by_domain"] = {
        domain: {
            "n": len(items),
            "domain@1": round(sum(bool(r["domain@1"]) for r in items) / len(items), 4),
            "kanun@5": round(sum(bool(r["kanun@5"]) for r in items) / len(items), 4),
        }
        for domain, items in sorted(by_domain.items())
    }

    by_level: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("typo_level"):
            by_level[str(row["typo_level"])].append(row)
    if by_level:
        out["by_typo_level"] = {
            level: {
                "n": len(items),
                "domain@1": round(sum(bool(r["domain@1"]) for r in items) / len(items), 4),
                "kanun@5": round(sum(bool(r["kanun@5"]) for r in items) / len(items), 4),
                "madde_recall@8": round(
                    sum(float(r.get("madde_recall@8", 0.0)) for r in items if r.get("n_expected_madde"))
                    / max(sum(1 for r in items if r.get("n_expected_madde")), 1),
                    4,
                ),
            }
            for level, items in sorted(by_level.items())
        }
    return out


async def _run_cases(
    cases: list[dict[str, Any]],
    *,
    mode: str,
    typo_enabled: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    os.environ["TYPO_TOLERANCE_ENABLED"] = "1" if typo_enabled else "0"
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for case in cases:
        sink = io.StringIO()
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                row = await _eval_one(case, mode=mode)
            if case.get("typo_level"):
                row["typo_level"] = case["typo_level"]
                row["clean_soru"] = case.get("clean_soru")
            rows.append(row)
        except Exception as exc:
            errors.append({"id": str(case.get("id", "")), "error": str(exc)})
    return rows, errors


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-version", default="v2")
    parser.add_argument("--typo-path", type=Path, default=Path("data/eval_benchmark/typo_cases.jsonl"))
    parser.add_argument("--mode", default="node", choices=["hybrid", "rerank", "node"])
    parser.add_argument("--out", type=Path, default=Path("eval/runs/typo_retrieval_compare.json"))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    logging.disable(logging.CRITICAL)
    clean_cases = _load_benchmark(args.clean_version)
    typo_cases = _load_benchmark(benchmark_path=args.typo_path)
    if args.limit > 0:
        clean_cases = clean_cases[: args.limit]
        typo_cases = typo_cases[: args.limit]

    runs: dict[str, dict[str, Any]] = {}
    for label, cases, enabled in (
        ("clean_enabled", clean_cases, True),
        ("clean_disabled", clean_cases, False),
        ("typo_enabled", typo_cases, True),
        ("typo_disabled", typo_cases, False),
    ):
        rows, errors = await _run_cases(cases, mode=args.mode, typo_enabled=enabled)
        runs[label] = {
            "summary": _summarize(rows, errors),
            "errors": errors[:20],
            "rows": rows,
        }
        print(f"{label}: {runs[label]['summary']}")

    payload = {
        "mode": args.mode,
        "clean_version": args.clean_version,
        "typo_path": str(args.typo_path),
        "runs": runs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
