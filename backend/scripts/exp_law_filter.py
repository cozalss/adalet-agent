"""DENEY: law-only filtre madde_recall@5'i yükseltiyor mu? (ölçüm-sürücülü RAG, 2026-06-04).

Hipotez: benchmark search() doc_type filtrelemiyor → case-law (anayasa, kanun_kodu=None) chunk'ları
top-5'i kirletip mevzuat maddelerini dışarı itiyor. Production mevzuat_node law-only filtreliyor →
benchmark production'ı OLDUĞUNDAN KÖTÜ gösteriyor olabilir. A/B: aynı retrieval, filtreli vs filtresiz.

Çalıştır: cd backend && uv run python -m scripts.exp_law_filter
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import core.native_preload  # noqa: F401
from retrieval.hybrid_search import search
from scripts.eval_run import _load_benchmark, madde_level_metrics


def _recall(res, kanun, madde):
    m = madde_level_metrics(res, kanun, madde)
    return m.get("madde_recall@5")


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cases = [c for c in _load_benchmark("v2") if c.get("expected_madde_no")]
    print(f"{len(cases)} madde-gold vaka · hybrid top-15 -> top-5 (filtresiz vs law-only)\n", flush=True)

    raw_by_dom: dict[str, list[float]] = defaultdict(list)
    law_by_dom: dict[str, list[float]] = defaultdict(list)
    for i, c in enumerate(cases, 1):
        res = await search(question=c["soru"], top_k=15, sparse_domain=c["expected_domain"])
        kanun, madde = c.get("expected_kanun", []), c.get("expected_madde_no", [])
        raw = _recall(res[:5], kanun, madde)
        law = _recall([r for r in res if (r.metadata or {}).get("kanun_kodu")][:5], kanun, madde)
        d = c["expected_domain"]
        if raw is not None:
            raw_by_dom[d].append(raw)
        if law is not None:
            law_by_dom[d].append(law)
        if i % 25 == 0:
            print(f"  ...{i}/{len(cases)}", flush=True)

    def _ov(by):
        allv = [v for vs in by.values() for v in vs]
        return sum(allv) / len(allv) if allv else 0.0

    bar = "=" * 60
    print(f"\n{bar}\n  LAW-FILTER DENEYİ — {len(cases)} vaka\n{bar}")
    print(f"  GENEL madde_recall@5:  filtresiz={_ov(raw_by_dom):.1%}   law-only={_ov(law_by_dom):.1%}")
    print(f"  {'-'*58}")
    print(f"  {'domain':12s} {'filtresiz':>10s} {'law-only':>10s} {'delta':>8s}")
    for d in sorted(raw_by_dom):
        r = sum(raw_by_dom[d]) / len(raw_by_dom[d])
        lw = sum(law_by_dom[d]) / len(law_by_dom[d]) if law_by_dom[d] else 0.0
        print(f"  {d:12s} {r:>10.1%} {lw:>10.1%} {(lw-r):>+8.1%}")
    print(bar)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
