"""Eval benchmark runner — 50 vakalık Türkçe hukuk RAG değerlendirmesi.

Her soru için:
- Hybrid search top-10
- Hybrid + Rerank top-5

Metrikler:
- Domain accuracy@1: ilk sonucun domain'i doğru mu?
- Domain accuracy@5: top-5'te doğru domain var mı?
- Kanun match@5: top-5'te beklenen kanun referansı var mı?
- Keyword recall: ground_truth_keywords kaçı top-5 metinlerinde geçiyor?
- MRR: ilk doğru-domain sonucun rank'i

Çalıştırma:
    uv run python -m scripts.eval_run [--rerank]
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

from agents.config import DOMAIN_TO_KANUN_KODU
from core import native_preload  # noqa: F401  — pyarrow'u torch'tan önce yükle (Windows)
from retrieval.hybrid_search import search, search_with_rerank

logger = logging.getLogger("eval")
BENCHMARK_DIR = Path(__file__).parent.parent / "data" / "eval_benchmark"
BENCHMARK_PATH = BENCHMARK_DIR / "benchmark.jsonl"      # v1 (50 vaka, legacy)
BENCHMARK_V2_PATH = BENCHMARK_DIR / "benchmark_v2.jsonl"  # v2 (186 vaka, Sprint-4 W2)

# kanun_kodu → bu kodu içeren domain'ler (reverse map). Kanun (mevzuat) chunk'ında
# `domain` payload alanı YOK → domain@1 metriği onları haksızca "miss" sayardı.
# Bu map ile bir kanun chunk'ı, kanun_kodu'su expected domain'in setindeyse "doğru
# domain" kabul edilir (adil ölçüm — retrieval doğru kanunu getirdiyse başarı).
_KODU_TO_DOMAINS: dict[str, tuple[str, ...]] = defaultdict(tuple)
for _dom, _kodlar in DOMAIN_TO_KANUN_KODU.items():
    for _kod in _kodlar:
        _KODU_TO_DOMAINS[_kod] = (*_KODU_TO_DOMAINS[_kod], _dom)


def _effective_domain(result: Any, expected_domain: str) -> str:
    """Chunk'ın efektif domain'i — case için payload.domain, kanun için kanun_kodu map.

    Kanun chunk'ında domain yok; kanun_kodu expected domain'e aitse expected
    döner (doğru kanun = doğru domain), değilse kodu içeren ilk domain.
    """
    dom = getattr(result, "domain", "") or ""
    if dom:
        return dom
    kod = result.metadata.get("kanun_kodu") if hasattr(result, "metadata") else None
    if kod:
        doms = _KODU_TO_DOMAINS.get(kod, ())
        if expected_domain in doms:
            return expected_domain
        return doms[0] if doms else ""
    return ""

# Retrieval modları — eval_one ve freeze_baseline ortak vocab
SearchMode = str  # "hybrid" | "rerank" | "hyde" | "multi_query"


def _load_benchmark(version: str = "v1") -> list[dict[str, Any]]:
    """JSONL benchmark dosyasını oku.

    Args:
        version: "v1" (default, eski 50 vaka) | "v2" (W2 expansion, 186 vaka)
    """
    path = BENCHMARK_V2_PATH if version == "v2" else BENCHMARK_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Benchmark dosyası bulunamadı: {path}. "
            f"v2 için önce `python -m scripts.merge_benchmark_v2` çalıştır.",
        )
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _keyword_recall(text: str, keywords: list[str]) -> float:
    """Türkçe morfo-aware keyword recall (Sprint-4 W1.5).

    Önceki davranış: case-insensitive substring → "kıdem tazminatı" beklerken
    cevap "kıdemin tazminatları" diye yazılı olursa miss. snowballstemmer +
    prefix-overlap ile çekimli formları aynı stem'e indirip recall ölçer.

    Fallback: stemmer unavailable → plain lower() substring (eski davranış).
    """
    if not keywords:
        return 0.0
    try:
        from retrieval.turkish_text import keyword_overlap
        return keyword_overlap(text, keywords, use_stem=True)
    except ImportError:
        text_low = text.lower()
        hits = sum(1 for kw in keywords if kw.lower() in text_low)
        return hits / len(keywords)


def madde_level_metrics(
    results: list[Any], expected_kanun: list, expected_madde_no: list, k: int = 5,
) -> dict[str, float]:
    """Madde-düzeyi recall@k + MRR — 8-yönlü domain proxy'sinden ÇOK daha sıkı (denetim 2026-06-04).

    Headline domain@k/MRR yalnız 'doğru topic'i ölçer: yanlış maddeyi içeren bir chunk bile
    'isabet' sayılır. Bu metrik 'doğru MADDEYİ getirdik mi'yi ölçer: chunk'ın (kanun_kodu,
    madde_no) metadata'sı beklenen kanun+madde gold'uyla eşleşmeli. Saf fonksiyon (Qdrant'sız
    test edilebilir). expected_madde_no boşsa {} döner → vaka madde-düzeyi ortalamadan hariç.
    """
    exp = {int(m) for m in (expected_madde_no or []) if str(m).strip().lstrip("-").isdigit()}
    if not exp:
        return {}
    got: set[int] = set()
    mrr = 0.0
    for i, r in enumerate(results[:k], 1):
        md = getattr(r, "metadata", None) or {}
        if expected_kanun and md.get("kanun_kodu") not in expected_kanun:
            continue
        try:
            mn = int(md.get("madde_no"))
        except (TypeError, ValueError):
            continue
        if mn in exp:
            got.add(mn)
            if mrr == 0.0:
                mrr = 1.0 / i
    return {
        f"madde_recall@{k}": round(len(got) / len(exp), 3),
        "madde_mrr": round(mrr, 3),
        "n_expected_madde": float(len(exp)),
    }


async def _eval_one(
    case: dict[str, Any],
    use_rerank: bool = False,
    mode: SearchMode | None = None,
) -> dict[str, Any]:
    """Tek vaka için retrieval + metrikler.

    Args:
        case: benchmark satırı (id, soru, expected_*, ground_truth_keywords)
        use_rerank: geriye-uyumluluk; True iken "rerank" mode'una eşdeğer
        mode: "hybrid" | "rerank" | "hyde" | "multi_query".
              None ise use_rerank flag'inden türetilir.
    """
    soru = case["soru"]
    expected_domain = case["expected_domain"]
    expected_kanun = case.get("expected_kanun", [])
    expected_madde_no = case.get("expected_madde_no", [])
    gt_keywords = case.get("ground_truth_keywords", [])

    # Mode resolution — use_rerank için geriye dönük tutarlılık
    if mode is None:
        mode = "rerank" if use_rerank else "hybrid"

    t0 = time.perf_counter()
    if mode == "rerank":
        results = await search_with_rerank(question=soru, top_k=5, candidates_n=20)
    elif mode == "hyde":
        from retrieval.hyde import search_with_hyde
        results = await search_with_hyde(soru, top_k=10)
    elif mode == "multi_query":
        from agents.config import MULTI_QUERY_N
        from retrieval.multi_query import search_multi_query
        results = await search_multi_query(soru, top_k=10, n_queries=MULTI_QUERY_N)
    else:  # "hybrid"
        results = await search(question=soru, top_k=10, sparse_domain=expected_domain)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Metrik hesapla — efektif domain (kanun chunk'ları kanun_kodu→domain ile maplenir;
    # ham r.domain kanunlarda boş olduğundan domain@1'i haksız düşürürdü).
    domains = [_effective_domain(r, expected_domain) for r in results]
    domain_at_1 = domains[0] == expected_domain if domains else False
    domain_at_5 = expected_domain in domains[:5]

    # Kanun match (mevzuat sonuçları için kanun_kodu field var)
    kanun_at_5 = False
    for r in results[:5]:
        kanun_kodu = r.metadata.get("kanun_kodu") if hasattr(r, "metadata") else None
        if kanun_kodu and kanun_kodu in expected_kanun:
            kanun_at_5 = True
            break

    # MRR — ilk doğru domain'in pozisyonu
    mrr = 0.0
    for i, d in enumerate(domains, 1):
        if d == expected_domain:
            mrr = 1.0 / i
            break

    # Keyword recall (top-5'in birleşik metni üzerinde)
    combined_text = " ".join(r.text for r in results[:5])
    kw_recall = _keyword_recall(combined_text, gt_keywords)

    # Sprint-4 W2.3: context_precision@5 — top-5 sonuçların kaçı expected
    # domain'le uyumlu (Ragas context_precision'ın retrieval-only versiyonu).
    # Tek-bit domain@K yerine "K-içinde-kalite oranı" — kanun bulunmasa bile
    # retrieval'ın doğru topic'te kalıp kalmadığını ölçer.
    top5 = domains[:5]
    n_relevant = sum(1 for d in top5 if d == expected_domain)
    context_precision_at_5 = n_relevant / 5.0 if top5 else 0.0

    # Madde-düzeyi (en sıkı): 'doğru maddeyi getirdik mi' — domain proxy'sini tamamlar.
    madde_metrics = madde_level_metrics(results, expected_kanun, expected_madde_no)

    return {
        "id": case["id"],
        "soru": soru,
        "expected_domain": expected_domain,
        "got_domains_top5": domains[:5],
        "domain@1": domain_at_1,
        "domain@5": domain_at_5,
        "kanun@5": kanun_at_5,
        "mrr": mrr,
        **madde_metrics,
        "keyword_recall": kw_recall,
        "context_precision@5": context_precision_at_5,
        "elapsed_ms": elapsed_ms,
    }


def _print_summary(results: list[dict[str, Any]], mode: str) -> None:
    n = len(results)
    if n == 0:
        print(f"\n=== {mode}: HİÇ SONUÇ YOK ===")
        return

    d1 = sum(r["domain@1"] for r in results) / n
    d5 = sum(r["domain@5"] for r in results) / n
    k5 = sum(r["kanun@5"] for r in results) / n
    mrr = sum(r["mrr"] for r in results) / n
    kwr = sum(r["keyword_recall"] for r in results) / n
    avg_ms = sum(r["elapsed_ms"] for r in results) / n
    p95_ms = sorted(r["elapsed_ms"] for r in results)[int(0.95 * n)] if n > 1 else avg_ms

    print(f"\n{'=' * 60}")
    print(f"  {mode}  —  {n} soru")
    print(f"{'=' * 60}")
    print(f"  Domain Accuracy @1 (top-1 doğru):   {d1*100:5.1f}%")
    print(f"  Domain Accuracy @5 (top-5'te var):  {d5*100:5.1f}%")
    print(f"  Kanun Match @5 (mevzuat döndü):     {k5*100:5.1f}%")
    print(f"  MRR (domain-düzeyi, proxy):         {mrr:.3f}")
    # Madde-düzeyi (en sıkı) — yalnız expected_madde_no taşıyan vakalar üzerinden.
    madde_cases = [r for r in results if r.get("n_expected_madde")]
    if madde_cases:
        m = len(madde_cases)
        mr5 = sum(r.get("madde_recall@5", 0.0) for r in madde_cases) / m
        mmrr = sum(r.get("madde_mrr", 0.0) for r in madde_cases) / m
        print(f"  Madde Recall @5 (DOĞRU madde):      {mr5*100:5.1f}%   ({m} vaka)")
        print(f"  Madde MRR (madde-düzeyi, SIKI):     {mmrr:.3f}")
    print(f"  Keyword Recall (gt kw in top-5):    {kwr*100:5.1f}%")
    print(f"  Avg latency:  {avg_ms:6.0f} ms   |   P95: {p95_ms:6.0f} ms")
    print()

    # Domain breakdown
    per_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        per_domain[r["expected_domain"]].append(r)

    print("  Domain bazlı domain@1 başarı oranı:")
    for dom, rs in sorted(per_domain.items()):
        ok = sum(r["domain@1"] for r in rs)
        print(f"    {dom:12s}  {ok:2d}/{len(rs):2d}  ({ok/len(rs)*100:5.1f}%)")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerank", action="store_true", help="Hybrid + cross-encoder rerank kullan")
    parser.add_argument("--version", choices=["v1", "v2"], default="v1",
                        help="Benchmark sürümü: v1 (50 vaka) | v2 (186 vaka, 8 domain)")
    parser.add_argument("--out", type=Path, default=None, help="Sonuçları JSON'a yaz")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    path = BENCHMARK_V2_PATH if args.version == "v2" else BENCHMARK_PATH
    print(f"Benchmark yükleniyor: {path}")
    cases = _load_benchmark(args.version)
    print(f"Toplam {len(cases)} soru\n")
    print(f"Mode: {'HYBRID + RERANK' if args.rerank else 'HYBRID (no rerank)'}")
    print()

    results: list[dict[str, Any]] = []
    for i, case in enumerate(cases, 1):
        print(f"[{i:2d}/{len(cases)}] {case['id']}  {case['soru'][:50]}", end=" ... ", flush=True)
        try:
            r = await _eval_one(case, use_rerank=args.rerank)
            results.append(r)
            mark = "OK" if r["domain@1"] else ("@5" if r["domain@5"] else "MISS")
            print(f"{mark}  ({r['elapsed_ms']:.0f}ms)")
        except Exception as exc:
            print(f"ERROR: {exc}")

    _print_summary(results, "HYBRID + RERANK" if args.rerank else "HYBRID")

    if args.out:
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nDetay yazıldı: {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
