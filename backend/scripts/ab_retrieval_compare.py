"""HyDE / Multi-Query A/B Karşılaştırma Aracı.

4 retrieval modunu 186-vakalık benchmark_v2 üzerinde karşılaştırır ve
Teknofest sunumu için markdown tablo üretir.

Modlar:
  baseline   — saf hybrid (BM25 + dense, rerank yok)
  hyde       — HyDE query expansion
  mq         — Multi-Query (5 paraphrase + RRF)
  both       — HyDE + Multi-Query paralel, RRF-birleştirme

Çalıştırma:
    uv run python -m scripts.ab_retrieval_compare
    uv run python -m scripts.ab_retrieval_compare --modes baseline,hyde
    uv run python -m scripts.ab_retrieval_compare --version v2 --out-dir eval/runs
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
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import native_preload  # noqa: F401 — pyarrow/torch Windows sırası
from scripts.eval_run import _eval_one, _load_benchmark

logger = logging.getLogger("ab_compare")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

EVAL_RUNS_DIR = Path(__file__).parent.parent / "eval" / "runs"
RRF_K = 60


# ---------------------------------------------------------------------------
# "both" modu: HyDE + MQ paralel, RRF birleştir
# ---------------------------------------------------------------------------

async def _search_both(question: str, top_k: int = 10) -> list[Any]:
    from agents.config import MULTI_QUERY_N
    from retrieval.hyde import search_with_hyde
    from retrieval.multi_query import search_multi_query

    hyde_task = asyncio.create_task(search_with_hyde(question, top_k=top_k * 3))
    mq_task = asyncio.create_task(
        search_multi_query(question, top_k=top_k * 3, n_queries=MULTI_QUERY_N)
    )
    results_list = await asyncio.gather(hyde_task, mq_task, return_exceptions=True)

    scores: dict[str, float] = defaultdict(float)
    id_to_result: dict[str, Any] = {}
    for results in results_list:
        if isinstance(results, Exception):
            logger.warning("both-mode alt sorgu başarısız: %s", results)
            continue
        for rank, r in enumerate(results, 1):
            rid = getattr(r, "id", None) or str(r)
            scores[rid] += 1.0 / (RRF_K + rank)
            id_to_result[rid] = r

    return sorted(
        id_to_result.values(),
        key=lambda r: scores[getattr(r, "id", str(r))],
        reverse=True,
    )[:top_k]


async def _eval_one_both(case: dict[str, Any]) -> dict[str, Any]:
    from scripts.eval_run import _effective_domain, _keyword_recall

    soru = case["soru"]
    expected_domain = case["expected_domain"]
    expected_kanun = case.get("expected_kanun", [])
    gt_keywords = case.get("ground_truth_keywords", [])

    t0 = time.perf_counter()
    results = await _search_both(soru, top_k=10)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    domains = [_effective_domain(r, expected_domain) for r in results]
    domain_at_1 = bool(domains and domains[0] == expected_domain)
    domain_at_5 = expected_domain in domains[:5]

    kanun_at_5 = any(
        r.metadata.get("kanun_kodu") in expected_kanun
        for r in results[:5]
        if hasattr(r, "metadata") and r.metadata.get("kanun_kodu")
    )

    mrr = next(
        (1.0 / i for i, d in enumerate(domains, 1) if d == expected_domain), 0.0
    )
    kw_recall = _keyword_recall(" ".join(getattr(r, "text", "") for r in results[:5]), gt_keywords)

    return {
        "id": case["id"],
        "expected_domain": expected_domain,
        "domain@1": domain_at_1,
        "domain@5": domain_at_5,
        "kanun@5": kanun_at_5,
        "mrr": mrr,
        "keyword_recall": kw_recall,
        "elapsed_ms": elapsed_ms,
        "mode": "both",
    }


# ---------------------------------------------------------------------------
# Benchmark koşucusu
# ---------------------------------------------------------------------------

async def _run_mode(
    mode: str,
    cases: list[dict[str, Any]],
    timeout_s: float = 60.0,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for i, case in enumerate(cases, 1):
        logger.info("[%s] %d/%d  id=%s", mode, i, len(cases), case["id"])
        try:
            if mode == "both":
                row = await asyncio.wait_for(_eval_one_both(case), timeout=timeout_s)
            else:
                eval_mode = "hybrid" if mode == "baseline" else mode
                row = await asyncio.wait_for(
                    _eval_one(case, mode=eval_mode), timeout=timeout_s
                )
            row["mode"] = mode
            results.append(row)
        except TimeoutError:
            logger.warning("[%s] TIMEOUT id=%s", mode, case["id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] HATA id=%s: %s", mode, case["id"], exc)
    return results


# ---------------------------------------------------------------------------
# İstatistikler
# ---------------------------------------------------------------------------

def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    n = len(rows)
    lats = sorted(r["elapsed_ms"] for r in rows)
    p95_idx = max(0, math.ceil(n * 0.95) - 1)
    return {
        "n": n,
        "domain@1": sum(r["domain@1"] for r in rows) / n,
        "domain@5": sum(r["domain@5"] for r in rows) / n,
        "kanun@5": sum(r["kanun@5"] for r in rows) / n,
        "mrr": sum(r["mrr"] for r in rows) / n,
        "keyword_recall": sum(r["keyword_recall"] for r in rows) / n,
        "lat_avg_ms": sum(lats) / n,
        "lat_p95_ms": lats[p95_idx],
    }


def _per_domain(rows: list[dict[str, Any]]) -> dict[str, float]:
    by_domain: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        by_domain[r["expected_domain"]].append(bool(r["domain@1"]))
    return {dom: sum(hits) / len(hits) for dom, hits in sorted(by_domain.items())}


# ---------------------------------------------------------------------------
# Markdown raporu
# ---------------------------------------------------------------------------

def _markdown_table(summaries: dict[str, dict[str, Any]]) -> str:
    cols = ["domain@1", "domain@5", "kanun@5", "mrr", "keyword_recall", "lat_avg_ms", "lat_p95_ms"]
    lines = [
        "| Mod | " + " | ".join(cols) + " |",
        "|" + "|".join(["---"] * (len(cols) + 1)) + "|",
    ]
    baseline = summaries.get("baseline", {})
    for mode, s in summaries.items():
        if not s:
            continue

        def _fmt(k: str, _s: dict = s, _mode: str = mode) -> str:  # bind loop vars
            v = _s.get(k, 0.0)
            b = baseline.get(k, 0.0)
            delta = v - b
            if k.startswith("lat"):
                sign = "+" if delta > 0 else ""
                return f"{v:.0f}ms ({sign}{delta:.0f})"
            sign = "+" if delta > 0 else ""
            pct = f" ({sign}{delta * 100:.1f}pp)" if _mode != "baseline" else ""
            return f"{v:.3f}{pct}"

        lines.append("| " + mode + " | " + " | ".join(_fmt(c) for c in cols) + " |")
    return "\n".join(lines)


def _build_report(
    summaries: dict[str, dict[str, Any]],
    per_domain_all: dict[str, dict[str, float]],
    timestamp: str,
    n_cases: int,
) -> str:
    domains = sorted({d for pd in per_domain_all.values() for d in pd})
    modes = list(per_domain_all.keys())
    domain_header = "| Domain | " + " | ".join(modes) + " |"
    domain_sep = "|" + "|".join(["---"] * (len(modes) + 1)) + "|"
    domain_rows = [
        "| " + dom + " | "
        + " | ".join(f"{per_domain_all[m].get(dom, 0.0):.3f}" for m in modes)
        + " |"
        for dom in domains
    ]
    return "\n".join([
        "# ADALET-AGENT Retrieval A/B Karşılaştırması",
        "",
        f"Tarih: {timestamp}  |  Benchmark: benchmark_v2.jsonl ({n_cases} vaka)",
        "",
        "## Özet Tablo",
        "",
        _markdown_table(summaries),
        "",
        "## Domain Bazlı domain@1",
        "",
        domain_header,
        domain_sep,
        *domain_rows,
        "",
        "## Yorum",
        "",
        "- **Baseline (hybrid)**: Referans; HyDE/MQ katkısı bu değere göre ölçülür.",
        "- **HyDE**: Citizen dil ↔ hukuki jargon köprüsü.",
        "- **Multi-Query (mq)**: Lexical varyasyon; +6pp recall@20 beklenir (RAG lit.).",
        "- **Both**: Sinerjik etki; yüksek latency trade-off.",
        "",
        "> Bu tablo `docs/ablation_study.md` §4 A/B bölümüne yapıştırılabilir.",
    ])


# ---------------------------------------------------------------------------
# Ana giriş
# ---------------------------------------------------------------------------

async def main(args: argparse.Namespace) -> None:
    cases = _load_benchmark(args.version)
    logger.info("Benchmark yüklendi: %d vaka (v%s)", len(cases), args.version)

    modes = [m.strip() for m in args.modes.split(",")]
    raw: dict[str, list[dict[str, Any]]] = {}
    for mode in modes:
        logger.info("=== MOD: %s ===", mode.upper())
        raw[mode] = await _run_mode(mode, cases, timeout_s=args.timeout)

    summaries = {m: _aggregate(rows) for m, rows in raw.items()}
    per_domain_all = {m: _per_domain(rows) for m, rows in raw.items()}

    print("\n" + "=" * 72)
    print("  RETRİEVAL A/B SONUÇLARI")
    print("=" * 72)
    for mode, s in summaries.items():
        if not s:
            continue
        print(
            f"  {mode:<12}  domain@1={s['domain@1']:.3f}  domain@5={s['domain@5']:.3f}"
            f"  kanun@5={s['kanun@5']:.3f}  MRR={s['mrr']:.3f}"
            f"  kw={s['keyword_recall']:.3f}  lat={s['lat_avg_ms']:.0f}ms"
        )
    print("=" * 72 + "\n")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = out_dir / f"ab_retrieval_{ts}.json"
    payload = {"summaries": summaries, "per_domain": per_domain_all, "raw": raw}
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path = out_dir / f"ab_retrieval_{ts}.md"
    md_path.write_text(
        _build_report(summaries, per_domain_all, ts, len(cases)),
        encoding="utf-8",
    )

    logger.info("JSON  → %s", json_path)
    logger.info("Rapor → %s", md_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrieval A/B Karşılaştırması")
    parser.add_argument("--version", default="v2", choices=["v1", "v2"])
    parser.add_argument("--modes", default="baseline,hyde,mq,both")
    parser.add_argument("--out-dir", default="eval/runs")
    parser.add_argument("--timeout", type=float, default=60.0)
    asyncio.run(main(parser.parse_args()))
