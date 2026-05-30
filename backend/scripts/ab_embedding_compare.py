"""BGE-M3 vs Mursit-Large-TR-Retrieval embedding A/B karşılaştırması.

NewMindAI Mecellem koleksiyonundan Mursit-Large-TR-Retrieval modeli (403M,
ModernBERT tabanlı, 112.7B token Türkçe corpus, 10.3M Yargıtay sekansı).
Kaynak: arXiv 2601.16018 — https://huggingface.co/newmindai/Mursit-Large-TR-Retrieval

Bu script sorgu-tarafı embedding kalitesini ölçer:
  - Her benchmark sorusunu hem BGE-M3 hem Mursit ile embed eder
  - Qdrant'ta her iki embedding ile arama yapar
  - Aynı metriklerle kıyaslar (domain@1, domain@5, kanun@5, MRR)
  - BGE-M3 vs Mursit farkını raporlar

UYARI: Mursit modeli ilk çalıştırmada ~1.6GB indirilir (HF cache).
        Corpus Mursit ile yeniden index edilmemiştir — sadece sorgu-tarafı karşılaştırma.

Çalıştırma:
    uv run python -m scripts.ab_embedding_compare --version v1
    uv run python -m scripts.ab_embedding_compare --version v2 --out-dir eval/runs
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

from core import native_preload  # noqa: F401
from scripts.eval_run import _effective_domain, _keyword_recall, _load_benchmark

logger = logging.getLogger("ab_embedding")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

MURSIT_MODEL = "newmindai/Mursit-Large-TR-Retrieval"
MURSIT_BASE_MODEL = "newmindai/Mursit-Base-TR-Retrieval"


def _load_mursit(model_name: str = MURSIT_MODEL):
    """Mursit modelini yükle (FlagEmbedding veya sentence-transformers)."""
    try:
        from FlagEmbedding import FlagModel
        model = FlagModel(model_name, use_fp16=True)
        logger.info("Mursit FlagEmbedding ile yüklendi: %s", model_name)
        return model, "flag"
    except ImportError:
        pass
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        logger.info("Mursit SentenceTransformer ile yüklendi: %s", model_name)
        return model, "st"
    except ImportError:
        pass
    raise RuntimeError(
        "FlagEmbedding veya sentence-transformers gerekli:\n"
        "  uv pip install FlagEmbedding\n"
        "  veya: uv pip install sentence-transformers"
    )


def _embed_mursit(model, model_type: str, texts: list[str]) -> list[list[float]]:
    if model_type == "flag":
        vecs = model.encode(texts, batch_size=4)
        return [v.tolist() for v in vecs]
    # sentence-transformers
    vecs = model.encode(texts, convert_to_numpy=True)
    return [v.tolist() for v in vecs]


async def _search_with_custom_embedding(
    embedding: list[float],
    top_k: int = 10,
    domain: str | None = None,
) -> list[Any]:
    """Özel bir embedding vektörüyle Qdrant'ta arama yap."""
    from qdrant_client.http.models import Filter, FieldCondition, MatchValue
    from retrieval.vector_store import get_client, COLLECTION_NAME

    qdrant = get_client()
    query_filter = None
    if domain:
        query_filter = Filter(
            must=[FieldCondition(key="domain", match=MatchValue(value=domain))]
        )

    hits = await qdrant.search(
        collection_name=COLLECTION_NAME,
        query_vector=("dense", embedding),
        limit=top_k,
        query_filter=query_filter,
        with_payload=True,
    )
    return hits


async def _eval_one_mursit(
    case: dict[str, Any],
    mursit_embedding: list[float],
    top_k: int = 10,
) -> dict[str, Any]:
    """Mursit embedding ile tek vaka değerlendirmesi."""
    expected_domain = case["expected_domain"]
    expected_kanun = case.get("expected_kanun", [])
    gt_keywords = case.get("ground_truth_keywords", [])

    t0 = time.perf_counter()
    try:
        hits = await _search_with_custom_embedding(mursit_embedding, top_k=top_k)
    except Exception as e:
        logger.warning("Mursit arama hatası id=%s: %s", case["id"], e)
        return {"id": case["id"], "expected_domain": expected_domain, "error": str(e),
                "domain@1": False, "domain@5": False, "kanun@5": False,
                "mrr": 0.0, "keyword_recall": 0.0, "elapsed_ms": 0.0}
    elapsed_ms = (time.perf_counter() - t0) * 1000

    class _FakeResult:
        def __init__(self, hit):
            p = hit.payload or {}
            self.domain = p.get("domain", "")
            self.text = p.get("text", "") or p.get("snippet", "")
            self.metadata = p

    results = [_FakeResult(h) for h in hits]
    domains = [_effective_domain(r, expected_domain) for r in results]
    domain_at_1 = bool(domains and domains[0] == expected_domain)
    domain_at_5 = expected_domain in domains[:5]
    kanun_at_5 = any(
        r.metadata.get("kanun_kodu") in expected_kanun
        for r in results[:5]
        if r.metadata.get("kanun_kodu")
    )
    mrr = next((1.0 / i for i, d in enumerate(domains, 1) if d == expected_domain), 0.0)
    kw_recall = _keyword_recall(" ".join(r.text for r in results[:5]), gt_keywords)

    return {
        "id": case["id"],
        "expected_domain": expected_domain,
        "domain@1": domain_at_1,
        "domain@5": domain_at_5,
        "kanun@5": kanun_at_5,
        "mrr": mrr,
        "keyword_recall": kw_recall,
        "elapsed_ms": elapsed_ms,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in rows if "error" not in r]
    if not rows:
        return {}
    n = len(rows)
    lats = sorted(r["elapsed_ms"] for r in rows)
    p95 = lats[max(0, math.ceil(n * 0.95) - 1)]
    return {
        "n": n,
        "domain@1": sum(r["domain@1"] for r in rows) / n,
        "domain@5": sum(r["domain@5"] for r in rows) / n,
        "kanun@5": sum(r["kanun@5"] for r in rows) / n,
        "mrr": sum(r["mrr"] for r in rows) / n,
        "keyword_recall": sum(r["keyword_recall"] for r in rows) / n,
        "lat_avg_ms": sum(lats) / n,
        "lat_p95_ms": p95,
    }


def _per_domain(rows: list[dict[str, Any]]) -> dict[str, float]:
    by: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        if "error" not in r:
            by[r["expected_domain"]].append(bool(r["domain@1"]))
    return {d: sum(hits) / len(hits) for d, hits in sorted(by.items())}


def _print_comparison(bge_s: dict, mursit_s: dict, model_name: str) -> None:
    print("\n" + "=" * 72)
    print(f"  BGE-M3  vs  {model_name.split('/')[-1]}")
    print("=" * 72)
    metrics = ["domain@1", "domain@5", "kanun@5", "mrr", "keyword_recall", "lat_avg_ms"]
    for m in metrics:
        b = bge_s.get(m, 0.0)
        mu = mursit_s.get(m, 0.0)
        delta = mu - b
        sign = "+" if delta > 0 else ""
        if m.endswith("_ms"):
            print(f"  {m:<20} BGE-M3={b:.0f}ms  Mursit={mu:.0f}ms  ({sign}{delta:.0f}ms)")
        else:
            print(f"  {m:<20} BGE-M3={b:.3f}  Mursit={mu:.3f}  ({sign}{delta*100:.1f}pp)")
    print("=" * 72 + "\n")


async def main(args: argparse.Namespace) -> None:
    cases = _load_benchmark(args.version)
    logger.info("Benchmark yüklendi: %d vaka", len(cases))

    # BGE-M3 baseline (eval_run.py'den)
    logger.info("=== BGE-M3 Baseline ===")
    from scripts.eval_run import _eval_one as _bge_eval
    bge_results = []
    for i, c in enumerate(cases, 1):
        logger.info("[BGE-M3] %d/%d %s", i, len(cases), c["id"])
        try:
            r = await asyncio.wait_for(_bge_eval(c, mode="hybrid"), timeout=30)
            bge_results.append(r)
        except Exception as e:
            logger.warning("BGE-M3 hata %s: %s", c["id"], e)

    # Mursit model yükle
    logger.info("=== Mursit model yükleniyor: %s ===", args.model)
    mursit_model, model_type = _load_mursit(args.model)

    # Tüm soruları Mursit ile embed et (batch)
    logger.info("Sorular embed ediliyor (%d)...", len(cases))
    questions = [c["soru"] for c in cases]
    mursit_embeddings = _embed_mursit(mursit_model, model_type, questions)
    logger.info("Embedding tamamlandı.")

    # Mursit ile arama
    logger.info("=== Mursit Arama ===")
    mursit_results = []
    for i, (c, emb) in enumerate(zip(cases, mursit_embeddings), 1):
        logger.info("[Mursit] %d/%d %s", i, len(cases), c["id"])
        r = await _eval_one_mursit(c, emb, top_k=10)
        mursit_results.append(r)

    bge_s = _aggregate(bge_results)
    mursit_s = _aggregate(mursit_results)
    _print_comparison(bge_s, mursit_s, args.model)

    # Domain kırılımı
    bge_pd = _per_domain(bge_results)
    mursit_pd = _per_domain(mursit_results)
    print("Domain bazlı domain@1:")
    domains = sorted(set(bge_pd) | set(mursit_pd))
    for d in domains:
        b = bge_pd.get(d, 0.0)
        m = mursit_pd.get(d, 0.0)
        sign = "+" if m - b > 0 else ""
        print(f"  {d:<14} BGE={b:.3f}  Mursit={m:.3f}  ({sign}{(m-b)*100:.1f}pp)")

    # Çıktı kaydet
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"ab_embedding_{ts}.json"
    out.write_text(
        json.dumps({
            "model": args.model,
            "bge_summary": bge_s,
            "mursit_summary": mursit_s,
            "bge_per_domain": bge_pd,
            "mursit_per_domain": mursit_pd,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Sonuç → %s", out)

    verdict = "MURSIT KAZANDI" if mursit_s.get("domain@1", 0) > bge_s.get("domain@1", 0) else "BGE-M3 DAHA İYİ"
    logger.info("KARAR: %s (domain@1 fark: %+.1fpp)",
                verdict, (mursit_s.get("domain@1", 0) - bge_s.get("domain@1", 0)) * 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BGE-M3 vs Mursit Embedding A/B")
    parser.add_argument("--version", default="v1", choices=["v1", "v2"])
    parser.add_argument("--model", default=MURSIT_MODEL,
                        help=f"Mursit model adı (default: {MURSIT_MODEL})")
    parser.add_argument("--out-dir", default="eval/runs")
    asyncio.run(main(parser.parse_args()))
