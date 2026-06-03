"""RAG ölçüm HIZLI-BAŞLANGIÇ — 'nasıl ölçerim' sorusunun çalışan cevabı.

Birkaç benchmark vakasında HYBRID retrieval koşar (LLM GEREKMEZ — yalnız Qdrant + embedder) ve
her vaka için domain@1 + madde_recall@5 gösterir. Tam ölçüm için scripts/eval_run.py kullan.

Çalıştır:  cd backend && uv run python -m scripts.demo_measure_rag
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")  # production config (mursit_hybrid, sparse...)

import core.native_preload  # noqa: E402,F401  (BGE-M3 import-sırası crash fix — bu kutuda gerekli)
from scripts.eval_run import _eval_one, _load_benchmark, _print_summary  # noqa: E402

_SPARSE = ("vergi", "trafik", "icra")


async def main() -> int:
    cases = _load_benchmark("v2")
    # Sparse-kritik domainlerden 5 + karışık 3 = 8 vaka (hızlı demo).
    pick = [c for c in cases if c.get("expected_domain") in _SPARSE][:5]
    pick += [c for c in cases if c.get("expected_domain") not in _SPARSE][:3]

    print(f"\n{len(pick)} vaka · HYBRID mode (LLM yok) · koleksiyon=mursit_hybrid\n")
    print(f"  {'id':12s} {'domain':10s} {'D@1':4s} {'madde_recall@5':16s} ms")
    print(f"  {'-'*12} {'-'*10} {'-'*4} {'-'*16} ----")
    results = []
    for c in pick:
        r = await _eval_one(c, mode="hybrid")
        results.append(r)
        mr = r.get("madde_recall@5")
        print(f"  {c['id']:12s} {c['expected_domain']:10s} "
              f"{int(r['domain@1']):<4d} {str(mr) if mr is not None else '-':16s} "
              f"{r['elapsed_ms']:.0f}")
    _print_summary(results, "hybrid (demo, 8 vaka)")
    print("\nTAM ölçüm: uv run python -m scripts.eval_run --version v2   (186 vaka)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
