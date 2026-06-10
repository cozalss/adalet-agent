"""Emsal (case-law) retrieval benchmark — production zinciri ölçümü (P5, 2026-06-10).

Korpusun %95'i case chunk'ı (152K) ama emsal retrieval kalitesinin HİÇ otomatik
metriği yoktu (39-soruluk coverage probe yalnız çıktı kaydediyordu, gold'suz).
Bu koşucu emsal_node'un gerçek ranking zincirini (rank_case_candidates: ana
hybrid+rerank → preferred-court scoped takviye → case filtre → tier-sort) 64
gold vakada ölçer. Canlı fallback (CRAG) ve graph kapsam DIŞI (network/opt-in).

Metrikler (madde-gold mevzuattaki gibi mümkün değil — "tek doğru karar" yok;
dürüst proxy'ler):
- court_match@3/@8: top-k'da DOMAIN_PREFERRED_COURTS kaynaklı karar var mı
  (tier-sort'un optimize ettiği eksen).
- topical@3/@8: top-k'da gold keyword'lerin ≥%50'sini içeren chunk var mı
  (stem-aware keyword_overlap; konu-alakası proxy'si — sınırı bilinen yöntem).
- best_overlap: top-8 içindeki en iyi chunk keyword örtüşmesi (sürekli sinyal).
- live_trigger_rate: en iyi rerank skoru EMSAL_LIVE_TRIGGER_SCORE altı vaka oranı
  (CRAG canlı fallback'in production'da ne sıklık tetikleneceği).

Çalıştırma (Qdrant + embedder gerekir, LLM gerekmez):
    uv run python -m scripts.eval_emsal [--out eval/runs/emsal_baseline.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from agents.config import EMSAL_LIVE_TRIGGER_SCORE, TOP_K_CASE
from core import native_preload  # noqa: F401  — pyarrow'u torch'tan önce yükle (Windows)

logger = logging.getLogger("eval_emsal")
BENCHMARK_PATH = (
    Path(__file__).parent.parent / "data" / "eval_benchmark" / "benchmark_emsal.jsonl"
)

# topical@k eşiği: chunk, gold keyword'lerin en az bu oranını içermeli.
TOPICAL_THRESHOLD = 0.5


def _overlap(text: str, keywords: list[str]) -> float:
    """Stem-aware keyword örtüşmesi (eval_run._keyword_recall ile aynı fallback)."""
    if not keywords:
        return 0.0
    try:
        from retrieval.turkish_text import keyword_overlap
        return keyword_overlap(text, keywords, use_stem=True)
    except ImportError:
        low = text.lower()
        return sum(1 for kw in keywords if kw.lower() in low) / len(keywords)


def case_metrics(
    results: list[Any], expected_sources: list[str], keywords: list[str],
) -> dict[str, Any]:
    """Tek vaka metrikleri — saf fonksiyon (Qdrant'sız test edilebilir).

    results: rank_case_candidates çıktısı (RerankResult benzeri: .source, .text,
    .score). top-8 (TOP_K_CASE) penceresi production'ın verify/draft'a verdiği havuz.
    """
    top = results[: TOP_K_CASE]
    exp = {s.lower() for s in expected_sources}

    def _court_at(k: int) -> bool:
        return any(str(r.source or "").lower() in exp for r in top[:k])

    overlaps = [_overlap(r.text, keywords) for r in top]
    best_overlap = max(overlaps, default=0.0)

    def _topical_at(k: int) -> bool:
        return any(o >= TOPICAL_THRESHOLD for o in overlaps[:k])

    best_score = max((float(r.score) for r in top), default=0.0)
    return {
        "n_results": len(top),
        "court@3": _court_at(3),
        "court@8": _court_at(8),
        "topical@3": _topical_at(3),
        "topical@8": _topical_at(8),
        "best_overlap": round(best_overlap, 3),
        "best_score": round(best_score, 4),
        "live_trigger": best_score < EMSAL_LIVE_TRIGGER_SCORE,
    }


def _load_benchmark() -> list[dict[str, Any]]:
    if not BENCHMARK_PATH.exists():
        raise FileNotFoundError(f"Benchmark yok: {BENCHMARK_PATH}")
    cases = []
    with BENCHMARK_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _print_summary(rows: list[dict[str, Any]]) -> None:
    n = len(rows)
    if not n:
        print("\nHİÇ SONUÇ YOK")
        return

    def avg(key: str) -> float:
        return sum(float(r[key]) for r in rows) / n

    print(f"\n{'=' * 60}")
    print(f"  EMSAL (production zinciri)  —  {n} soru")
    print(f"{'=' * 60}")
    print(f"  Court Match @3 (tercihli mahkeme):  {avg('court@3')*100:5.1f}%")
    print(f"  Court Match @8 (prod TOP_K_CASE):   {avg('court@8')*100:5.1f}%")
    print(f"  Topical @3 (keyword ≥{TOPICAL_THRESHOLD:.0%}):         {avg('topical@3')*100:5.1f}%")
    print(f"  Topical @8 (prod penceresi):        {avg('topical@8')*100:5.1f}%")
    print(f"  Best keyword overlap (ort):         {avg('best_overlap')*100:5.1f}%")
    print(f"  Live-fallback tetiklenme oranı:     {avg('live_trigger')*100:5.1f}%"
          f"   (skor < {EMSAL_LIVE_TRIGGER_SCORE})")
    print(f"  Avg latency:  {avg('elapsed_ms'):6.0f} ms")
    print()
    per_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        per_domain[r["expected_domain"]].append(r)
    print("  Domain bazlı topical@8 / court@8:")
    for dom, rs in sorted(per_domain.items()):
        t = sum(r["topical@8"] for r in rs)
        c = sum(r["court@8"] for r in rs)
        print(f"    {dom:12s}  topical {t}/{len(rs)}   court {c}/{len(rs)}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="Sonuçları JSON'a yaz")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    from agents.nodes.emsal import rank_case_candidates

    cases = _load_benchmark()
    print(f"Benchmark: {BENCHMARK_PATH} — {len(cases)} soru\n")

    rows: list[dict[str, Any]] = []
    for i, case in enumerate(cases, 1):
        print(f"[{i:2d}/{len(cases)}] {case['id']:18s} {case['soru'][:44]}",
              end=" ... ", flush=True)
        t0 = time.perf_counter()
        try:
            results, _, _ = await rank_case_candidates(case["soru"], case["expected_domain"])
        except Exception as exc:
            print(f"ERROR: {exc}")
            continue
        elapsed_ms = (time.perf_counter() - t0) * 1000
        m = case_metrics(results, case["expected_sources"], case["ground_truth_keywords"])
        rows.append({
            "id": case["id"],
            "soru": case["soru"],
            "expected_domain": case["expected_domain"],
            **m,
            "elapsed_ms": elapsed_ms,
            "top3": [
                {"source": r.source, "score": round(float(r.score), 3),
                 "title": (r.metadata.get("title") or "")[:70]}
                for r in results[:3]
            ],
        })
        mark = "OK" if m["topical@8"] else ("crt" if m["court@8"] else "MISS")
        print(f"{mark}  ({elapsed_ms:.0f}ms)")

    _print_summary(rows)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nDetay yazıldı: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
