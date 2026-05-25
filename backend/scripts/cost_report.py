"""Cost report — Sprint-4 W8.6.

Langfuse trace'lerden son N gün için token kullanımı + maliyet özeti.
ENV `LANGFUSE_PUBLIC_KEY` ve `_SECRET_KEY` şart.

Çıktı: eval/runs/cost_<date>.json
  {
    "from": "2026-05-18", "to": "2026-05-25",
    "n_traces": 1234, "total_input_tokens": ..., "total_output_tokens": ...,
    "estimated_cost_usd": ..., "per_user_top10": [...],
  }

Pricing tahmini (default Qwen lokal → $0 input/output, ENV ile override).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Default lokal Qwen — para harcamıyoruz; ENV ile cloud LLM pricing girilebilir
DEFAULT_PRICE_INPUT_PER_1K = float(os.getenv("PRICE_INPUT_PER_1K", "0.0"))
DEFAULT_PRICE_OUTPUT_PER_1K = float(os.getenv("PRICE_OUTPUT_PER_1K", "0.0"))


def fetch_traces(from_iso: str, to_iso: str, limit: int = 5000) -> list[dict]:
    """Langfuse SDK ile trace listesi. SDK yoksa boş döner."""
    try:
        from langfuse import Langfuse  # type: ignore[import-not-found]
    except ImportError:
        print("[cost] langfuse paketi yok — `uv add langfuse`", file=sys.stderr)
        return []

    pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = os.environ.get("LANGFUSE_SECRET_KEY")
    if not (pk and sk):
        print("[cost] LANGFUSE keys yok", file=sys.stderr)
        return []

    client = Langfuse(
        public_key=pk, secret_key=sk,
        host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    )
    # SDK API surface'ı versiyon bazlı değişiyor; fetch_traces / get_traces / list_traces
    for attr in ("fetch_traces", "get_traces", "list_traces"):
        method = getattr(client, attr, None)
        if callable(method):
            try:
                result = method(from_timestamp=from_iso, to_timestamp=to_iso, limit=limit)
                return list(result.data) if hasattr(result, "data") else list(result)
            except Exception as exc:
                print(f"[cost] {attr} failed: {exc}", file=sys.stderr)
                continue
    return []


def aggregate(traces: list[dict]) -> dict:
    """Trace listesini topla."""
    total_input = 0
    total_output = 0
    per_user: dict[str, dict[str, int]] = defaultdict(lambda: {"in": 0, "out": 0, "n": 0})

    for t in traces:
        usage = t.get("usage") or {}
        # Langfuse usage schema: input / output / total
        inp = int(usage.get("input", 0) or 0)
        outp = int(usage.get("output", 0) or 0)
        total_input += inp
        total_output += outp
        user = str(t.get("user_id") or "anon")
        per_user[user]["in"] += inp
        per_user[user]["out"] += outp
        per_user[user]["n"] += 1

    top10 = sorted(
        per_user.items(), key=lambda kv: kv[1]["in"] + kv[1]["out"], reverse=True,
    )[:10]

    cost = (
        (total_input / 1000) * DEFAULT_PRICE_INPUT_PER_1K
        + (total_output / 1000) * DEFAULT_PRICE_OUTPUT_PER_1K
    )
    return {
        "n_traces": len(traces),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "estimated_cost_usd": round(cost, 4),
        "price_input_per_1k": DEFAULT_PRICE_INPUT_PER_1K,
        "price_output_per_1k": DEFAULT_PRICE_OUTPUT_PER_1K,
        "per_user_top10": [
            {"user_id": u, **v} for u, v in top10
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Cost report from Langfuse")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--out",
        default=os.environ.get("COST_REPORT_DIR", "eval/runs"),
    )
    args = parser.parse_args()

    now = datetime.now(UTC)
    frm = now - timedelta(days=args.days)
    traces = fetch_traces(frm.isoformat(), now.isoformat())
    if not traces:
        print("[cost] no traces (likely no Langfuse config)")
    report = {
        "from": frm.date().isoformat(),
        "to": now.date().isoformat(),
        **aggregate(traces),
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"cost_{now.strftime('%Y%m%d')}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[cost] {report['n_traces']} traces, "
          f"{report['total_tokens']:,} tokens, "
          f"${report['estimated_cost_usd']:.4f}")
    print(f"[cost] → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
