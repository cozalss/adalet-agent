"""Reranker smoke test — Türk hukuk sorularıyla hybrid+rerank pipeline.

İlk çalıştırmada BGE-Reranker-v2-m3 (~1.1GB) iner. Sonra cache'lenir.

Test soruları gerçek vatandaş kullanım senaryolarını yansıtır.
"""

from __future__ import annotations

import asyncio
import time

from retrieval.hybrid_search import search, search_with_rerank

TEST_QUERIES = [
    ("kıdem tazminatı nasıl hesaplanır", "isHukuku"),
    ("ev sahibi kiracıyı nasıl tahliye edebilir", "kira"),
    ("ayıplı malda iade hakkı kaç gün", "tuketici"),
    ("trafik kazasında manevi tazminat", "trafik"),
    ("ödeme emrine itiraz süresi", "icra"),
]


async def main() -> None:
    print("=" * 70)
    print("HYBRID SEARCH vs HYBRID + RERANK karşılaştırması")
    print("=" * 70)

    for query, domain in TEST_QUERIES:
        print(f"\n[Q] Soru: {query!r}  (domain={domain})")
        print("-" * 70)

        # 1. Sadece hybrid (mevcut)
        t0 = time.perf_counter()
        hybrid_results = await search(question=query, top_k=5, domain=domain)
        hybrid_ms = (time.perf_counter() - t0) * 1000
        print(f"\n[HYBRID] {hybrid_ms:.0f}ms — top 3:")
        for i, r in enumerate(hybrid_results[:3], 1):
            preview = r.text.replace("\n", " ")[:100]
            print(f"  {i}. score={r.score:.3f}  {preview}...")

        # 2. Hybrid + Rerank (yeni)
        t0 = time.perf_counter()
        rerank_results = await search_with_rerank(
            question=query, top_k=5, candidates_n=20, domain=domain
        )
        rerank_ms = (time.perf_counter() - t0) * 1000
        print(f"\n[RERANK] {rerank_ms:.0f}ms — top 3:")
        for i, r in enumerate(rerank_results[:3], 1):
            preview = r.text.replace("\n", " ")[:100]
            print(
                f"  {i}. rerank={r.score:.3f}  orig={r.original_score:.3f}  {preview}..."
            )

        # Sıralama değişti mi?
        hybrid_ids = [r.chunk_id for r in hybrid_results[:3]]
        rerank_ids = [r.chunk_id for r in rerank_results[:3]]
        if hybrid_ids != rerank_ids:
            print("\n  [OK] Sıralama değişti — rerank top-3 farklı")
        else:
            print("\n  [--] Aynı top-3")

    print("\n" + "=" * 70)
    print("TEST BİTTİ")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
