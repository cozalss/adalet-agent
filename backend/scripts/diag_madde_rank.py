# -*- coding: utf-8 -*-
"""TEŞHİS (read-only): holdout madde@8 başarısızlıklarında gold maddenin
havuz-sırası + rerank-sonrası konumu. Kök-neden: pool'da yok (recall tavanı) /
pool'da var top-8 dışı (rerank düzeltilebilir)."""
import asyncio, os, sys
from collections import Counter
SPLIT = sys.argv[1] if len(sys.argv) > 1 else "holdout"

from core import native_preload  # noqa: F401  (Windows pyarrow<torch)
from scripts.eval_run import _load_benchmark, _split_of
from retrieval.hybrid_search import search
from agents.nodes.mevzuat import (MEVZUAT_DOC_TYPES, apply_step_back,
                                  mevzuat_pool_k, rank_law_candidates)

DEEP_POOL = 60  # recall tavanı kontrolü için geniş havuz

def _km(r):
    md = r.metadata if hasattr(r, "metadata") else {}
    return (md.get("kanun_kodu"), md.get("madde_no"))

async def main():
    cases = [c for c in _load_benchmark("v3") if _split_of(c) == SPLIT]
    cases = [c for c in cases if c.get("expected_madde_no")]  # madde-gold var
    print(f"holdout madde-gold vaka: {len(cases)}")
    buckets = Counter()
    detail = []
    for c in cases:
        soru = c["soru"]; dom = c["expected_domain"]
        exp = [(k, int(m) if str(m).isdigit() else m)
               for k in c.get("expected_kanun", []) for m in c.get("expected_madde_no", [])]
        # production zinciri (top-8 penceresi)
        pool = await search(question=soru, top_k=mevzuat_pool_k(),
                            sparse_domain=dom, doc_type=MEVZUAT_DOC_TYPES)
        pool, rq, rm = await apply_step_back(soru, dom, pool, "hybrid")
        ranked = await rank_law_candidates(soru, dom, pool, rm, rerank_query=rq)
        top8 = set(_km(r) for r in ranked[:8])
        # derin havuz (recall tavanı): geniş ham hybrid
        deep = await search(question=soru, top_k=DEEP_POOL, sparse_domain=dom,
                            doc_type=MEVZUAT_DOC_TYPES)
        deep_km = [_km(r) for r in deep]
        pool_km = [_km(r) for r in pool]
        for k, m in exp:
            tgt = (k, m)
            if tgt in top8:
                buckets["PASS_top8"] += 1; continue
            # başarısız — nerede?
            in_pool = tgt in pool_km
            in_deep = tgt in deep_km
            deep_rank = deep_km.index(tgt) + 1 if in_deep else None
            if in_pool:
                buckets["FAIL_pool'da_var_rerank_top8_dışı"] += 1
                cat = "rerank"
            elif in_deep:
                buckets[f"FAIL_pool_dışı_ama_deep{DEEP_POOL}'da(rank{deep_rank})"] += 1
                cat = "pool_kısa"
            else:
                buckets[f"FAIL_deep{DEEP_POOL}'da_bile_YOK"] += 1
                cat = "recall_tavan"
            detail.append((dom, k, m, cat, deep_rank, soru[:45]))
    print("\n=== KÖK-NEDEN DAĞILIMI (expected madde başına) ===")
    for kk, n in buckets.most_common():
        print(f"  {kk}: {n}")
    print("\n=== BAŞARISIZ DETAY ===")
    for dom, k, m, cat, dr, soru in detail:
        print(f"  [{dom}] {k} m.{m} | {cat}{' (deep#'+str(dr)+')' if dr else ''} | {soru}")

asyncio.run(main())
