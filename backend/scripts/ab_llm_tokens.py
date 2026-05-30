"""LLM token bütçesi ölçümü — P95 latans vs cevap kesilme vs kalite.

LLM üretimi uçtan uca latansın ~%80'i (Qwen 14B, 320 token ≈ 9.5s). Token
limitini düşürmek latansı azaltır ama cevabı kesebilir (truncation) ve kaliteyi
düşürebilir. Bu harness TEK token ayarını ölçer (LLM_MAX_TOKENS env'inden, başlatma
anında okunur — draft.py import-time bind ettiği için reload güvenilmez).

A/B için iki kez çalıştır, JSON çıktılarını karşılaştır:
    LLM_MAX_TOKENS=320 ... uv run python -m scripts.ab_llm_tokens --n 15 --out eval/runs/tok320.json
    LLM_MAX_TOKENS=240 ... uv run python -m scripts.ab_llm_tokens --n 15 --out eval/runs/tok240.json
    uv run python -m scripts.ab_llm_tokens --compare eval/runs/tok320.json eval/runs/tok240.json

NOT (model kısıtı): Bu kutuda yalnız Qwen 14B Q5_K_M var. Qwen 7B karşılaştırması
için ayrı GGUF + farklı portta llama-server gerekir (TODO — model swap).

Ölçülen: P50/P95/P99 latans, cevap kesilme oranı (is_truncated), kalite
(kısa-cevap, Türkçe-saflık, kaynak-bağı, hedef-uzunluk, kelime).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import native_preload  # noqa: F401

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logger = logging.getLogger("ab_llm_tokens")
logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")


def _percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[max(0, math.ceil(len(s) * p) - 1)]


async def _measure(args: argparse.Namespace) -> None:
    from agents.config import LLM_MAX_TOKENS  # başlatma anında env'den okundu
    from agents.graph import build_graph
    from agents.state import AgentState
    from eval.draft_quality import measure
    from scripts.eval_run import _load_benchmark

    cases = _load_benchmark(args.version)[:args.n]
    graph = build_graph()

    print(f"LLM_MAX_TOKENS={LLM_MAX_TOKENS}  ({len(cases)} vaka)", flush=True)
    await graph.ainvoke(AgentState(question="kıdem tazminatı nedir"))  # ısınma

    rows = []
    for i, case in enumerate(cases, 1):
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                graph.ainvoke(AgentState(question=case["soru"])), timeout=90)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            m = measure(result.get("response", "") or "")
            rows.append({"elapsed_ms": elapsed_ms,
                         "verdict": result.get("debate_verdict", "?"), **m})
            trunc = "TRUNC" if m.get("is_truncated") else ""
            print(f"  [{i:>2}/{len(cases)}] {elapsed_ms:>7.0f}ms  {m['word_count']}w {trunc}",
                  flush=True)
        except asyncio.TimeoutError:
            rows.append({"elapsed_ms": 90000, "is_truncated": False, "word_count": 0,
                         "has_short_answer": False, "turkish_purity": 0,
                         "src_coverage": 0, "length_in_target": False})

    legal = [r for r in rows if r["elapsed_ms"] > 1000]
    lats = [r["elapsed_ms"] for r in legal]
    n = len(legal) or 1
    summary = {
        "tokens": LLM_MAX_TOKENS,
        "model": "Qwen2.5-14B-Q5_K_M",
        "n_legal": len(legal),
        "p50_ms": round(_percentile(lats, 0.50)),
        "p95_ms": round(_percentile(lats, 0.95)),
        "p99_ms": round(_percentile(lats, 0.99)),
        "avg_ms": round(sum(lats) / n),
        "truncation_rate": round(sum(r.get("is_truncated", False) for r in legal) / n, 3),
        "short_answer_rate": round(sum(r["has_short_answer"] for r in legal) / n, 3),
        "avg_turkish_purity": round(sum(r["turkish_purity"] for r in legal) / n, 3),
        "avg_src_coverage": round(sum(r["src_coverage"] for r in legal) / n, 3),
        "length_in_target_rate": round(sum(r["length_in_target"] for r in legal) / n, 3),
        "avg_word_count": round(sum(r["word_count"] for r in legal) / n, 1),
    }

    print(f"\n  P50={summary['p50_ms']}ms P95={summary['p95_ms']}ms "
          f"kesilme={summary['truncation_rate']:.0%} "
          f"kısa-cvp={summary['short_answer_rate']:.0%} "
          f"uzunluk={summary['length_in_target_rate']:.0%}", flush=True)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Sonuc -> {out}", flush=True)


def _compare(paths: list[str]) -> None:
    rows = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    print(f"\n{'=' * 76}")
    print(f"  LLM TOKEN A/B — {rows[0]['model']} (model sabit)")
    print(f"{'=' * 76}")
    print(f"  {'token':>6} {'P50':>7} {'P95':>7} {'P99':>7} {'kesilme':>8} "
          f"{'kısa-cvp':>9} {'TR-saf':>7} {'src':>6} {'uzunluk':>8} {'kelime':>7}")
    for r in rows:
        print(f"  {r['tokens']:>6} {r['p50_ms']:>7} {r['p95_ms']:>7} {r['p99_ms']:>7} "
              f"{r['truncation_rate']:>7.0%} {r['short_answer_rate']:>8.0%} "
              f"{r['avg_turkish_purity']:>6.0%} {r['avg_src_coverage']:>5.0%} "
              f"{r['length_in_target_rate']:>7.0%} {r['avg_word_count']:>7}")
    print(f"{'=' * 76}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM token bütçesi ölçümü (tek ayar)")
    parser.add_argument("--version", default="v1", choices=["v1", "v2"])
    parser.add_argument("--n", type=int, default=15)
    parser.add_argument("--out", default=None)
    parser.add_argument("--compare", nargs="+", help="JSON çıktıları karşılaştır")
    a = parser.parse_args()
    if a.compare:
        _compare(a.compare)
    else:
        asyncio.run(_measure(a))
