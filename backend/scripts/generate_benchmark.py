"""Programmatic benchmark generator — Sprint-4 W2.1.

`data/eval_benchmark/topics_v2.json` domain → phrase listesinden vaka üretir.
İki mod:

    --offline (default): phrase + topic metadata'sından deterministic vaka
                          üretir. Network gerektirmez.
    --online:            yargi-mcp ile her phrase için bir karar fetch eder,
                          ground_truth_keywords'i karar text'inden zenginleştirir.

Çıkış: `data/eval_benchmark/benchmark_v2_generated.jsonl`

Akış:
    1. topics_v2.json oku → her domain için phrase listesi
    2. Her phrase için:
         id = "G{domain_prefix}{seq}"     (G_isHukuku_001, G_tuketici_001, …)
         soru = phrase'in soru-formuna dönüşmüş hali
         expected_domain = domain
         expected_kanun = topic'in kanun_kodu_map'ten gelen kodu (str)
         expected_madde_no = topic.expected_madde
         ground_truth_keywords = topic.keywords (+ online modda fetched text keywords)
    3. JSONL yaz; merge_benchmark_v2.py ile mevcut 50 vaka birleştirilir.

Çalıştırma:
    uv run python -m scripts.generate_benchmark             # offline default
    uv run python -m scripts.generate_benchmark --online    # +yargi-mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
TOPICS_PATH = REPO_ROOT / "data" / "eval_benchmark" / "topics_v2.json"
OUT_PATH = REPO_ROOT / "data" / "eval_benchmark" / "benchmark_v2_generated.jsonl"

DOMAIN_TO_KANUN_ABBR: dict[str, str] = {
    # Benchmark.jsonl mevcut kanun kısaltma stili (IK, TKHK, TBK, ...) korumak için.
    # Numeric kanun_kodu mapping `agents.config.DOMAIN_TO_KANUN_KODU` ile aynı.
    "isHukuku": "IK",
    "tuketici": "TKHK",
    "kira": "TBK",
    "icra": "IIK",
    "trafik": "KTK",
    "vergi": "VUK",
    "tapu": "TMK",
    "idari": "IYUK",
}

# Phrase → soru-formu dönüşüm template'leri (deterministic; LLM-siz).
# Her phrase bir konu özlü ifade — fiil ekiyle soru hâline getirilir.
_QUESTION_PATTERNS: list[tuple[str, list[str]]] = [
    # Pattern (regex prefix/suffix) → variant template listesi.
    # Her topic için max N varyant alınır; ilk eşleşen pattern grubu kullanılır.
    (r"\btazminatı?$",       [
        "{phrase} nasıl hesaplanır?",
        "{phrase} hangi durumda talep edilebilir?",
        "{phrase} için zamanaşımı süresi nedir?",
    ]),
    (r"\bdavası?$",          [
        "{phrase} nasıl açılır?",
        "{phrase} için hangi mahkeme yetkilidir?",
        "{phrase} sonucunda neler talep edilebilir?",
    ]),
    (r"\biadesi?$",          [
        "{phrase} hangi koşullarda yapılır?",
        "{phrase} için süre sınırı var mıdır?",
    ]),
    (r"\bsüresi?$",          [
        "{phrase} ne kadardır?",
        "{phrase} aşılırsa ne olur?",
    ]),
    (r"\bhakkı?$",           [
        "{phrase} hangi durumda kullanılır?",
        "{phrase} ne zaman doğar?",
    ]),
    (r"\bfeshi?$",           [
        "{phrase} hangi koşullarda mümkündür?",
        "{phrase} bildirim süreleri nelerdir?",
    ]),
    (r"\bcayma$",            [
        "{phrase} hakkı nasıl kullanılır?",
        "{phrase} hakkı kaç gün içinde kullanılmalıdır?",
    ]),
    (r"\bbeyanı?$",          [
        "{phrase} nasıl yapılır?",
        "{phrase} eksik yapıldığında ne olur?",
    ]),
    (r"\bartış oranı$",      [
        "{phrase} nasıl belirlenir?",
        "{phrase} yasal sınırı nedir?",
    ]),
    (r"\bbaşvuru$",          [
        "{phrase} prosedürü nedir?",
        "{phrase} için gereken belgeler nelerdir?",
    ]),
    (r"\bteslimat eksik$",   [
        "{phrase} durumunda tüketici hakları nelerdir?",
        "{phrase} olunca tüketici nasıl ispat eder?",
    ]),
    (r"\bödeneği?$",          [
        "{phrase} kimlere verilir?",
        "{phrase} miktarı nasıl hesaplanır?",
    ]),
    (r"\borantısız?$",       [
        "{phrase} olduğunda ne yapılır?",
        "{phrase} durumu ispatlanır mı?",
    ]),
]
_FALLBACK_TEMPLATES: list[str] = [
    "{phrase} hakkında ne yapılabilir?",
    "{phrase} konusunda hangi haklar mevcuttur?",
    "{phrase} için yasal süreç nasıl işler?",
]


def _phrase_to_questions(phrase: str, n: int) -> list[str]:
    """Phrase'ten n adet varyant soru üret (deterministic).

    İlk eşleşen pattern grubunun ilk n template'ini kullanır. Pattern
    eşleşmezse fallback template listesinden çeker. n > pattern_count
    olursa fallback ile pad'lemez; sadece pattern_count kadar döner
    (dolayısıyla bazı topic'ler için n elementten az dönebilir).
    """
    lo = phrase.strip().lower()
    for pattern, templates in _QUESTION_PATTERNS:
        if re.search(pattern, lo):
            return [t.format(phrase=phrase) for t in templates[:n]]
    return [t.format(phrase=phrase) for t in _FALLBACK_TEMPLATES[:n]]


def _build_cases_for_topic(
    domain: str,
    seq_start: int,
    topic: dict[str, Any],
    variants: int,
) -> list[dict[str, Any]]:
    """Tek topic → variants kadar benchmark case dict listesi."""
    kanun_abbr = DOMAIN_TO_KANUN_ABBR.get(domain, domain.upper())
    questions = _phrase_to_questions(topic["phrase"], variants)
    cases: list[dict[str, Any]] = []
    for i, q in enumerate(questions, 0):
        cases.append({
            "id": f"G_{domain}_{seq_start + i:03d}",
            "soru": q,
            "expected_domain": domain,
            "expected_kanun": [kanun_abbr],
            "expected_madde_no": list(topic.get("expected_madde", [])),
            "ground_truth_keywords": list(topic.get("keywords", [])),
            "source": "programmatic_v2",
            "topic_phrase": topic["phrase"],   # debug / regroup için
        })
    return cases


async def _enrich_online(
    cases: list[dict[str, Any]], max_concurrent: int = 4,
) -> list[dict[str, Any]]:
    """yargi-mcp ile her vaka için bir karar fetch + keyword zenginleştirme.

    Network hatası tek vakayı atlar, geri kalanı korur. Tenacity yargi_client
    içinde zaten retry yapıyor.
    """
    try:
        from retrieval.yargi_client import YargiClient
    except ImportError as exc:
        print(f"[!] yargi_client import edilemedi: {exc}", file=sys.stderr)
        return cases

    sem = asyncio.Semaphore(max_concurrent)

    async def _enrich_one(client: YargiClient, case: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            try:
                phrase = case["soru"].split("?")[0].strip()
                results = await client.search_yargitay(phrase, page_size=1)
            except (ConnectionError, TimeoutError, OSError) as exc:
                print(f"[!] {case['id']} yargi fetch failed: {exc}", file=sys.stderr)
                return case
            if not results:
                return case
            d = results[0]
            title = getattr(d, "title", "") or ""
            extra_kw = [w.strip() for w in title.split() if len(w) >= 4][:5]
            existing = case.get("ground_truth_keywords", []) or []
            merged = list(dict.fromkeys(existing + extra_kw))
            case["ground_truth_keywords"] = merged[:8]
            case["yargitay_ref"] = getattr(d, "document_id", "") or ""
            return case

    async with YargiClient() as client:
        tasks = [_enrich_one(client, c) for c in cases]
        return await asyncio.gather(*tasks)


def _load_topics() -> dict[str, Any]:
    return json.loads(TOPICS_PATH.read_text(encoding="utf-8"))


def _generate_offline(topics: dict[str, Any], variants: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for domain, topic_list in topics["domains"].items():
        seq = 1
        for topic in topic_list:
            new_cases = _build_cases_for_topic(domain, seq, topic, variants)
            cases.extend(new_cases)
            seq += len(new_cases)
    return cases


async def main_async() -> int:
    parser = argparse.ArgumentParser(
        description="Programmatic benchmark generation (Sprint-4 W2.1)",
    )
    parser.add_argument("--online", action="store_true",
                        help="yargi-mcp ile keyword zenginleştir (network gerekir)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Sadece ilk N vakayı üret (debug için)")
    parser.add_argument("--variants", type=int, default=2,
                        help="Topic başına soru varyant sayısı (default: 2)")
    args = parser.parse_args()

    if args.variants < 1:
        raise SystemExit("--variants en az 1 olmalı")

    topics = _load_topics()
    cases = _generate_offline(topics, variants=args.variants)
    if args.limit:
        cases = cases[: args.limit]
    print(f"[*] {len(cases)} vaka offline üretildi.")

    if args.online:
        print("[*] Online enrichment: yargi-mcp ile keyword zenginleştirme...")
        cases = await _enrich_online(cases)
        n_enriched = sum(1 for c in cases if c.get("yargitay_ref"))
        print(f"[*] Online enrichment: {n_enriched}/{len(cases)} vaka karar referansı aldı.")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"[OK] Yazıldı: {OUT_PATH} ({len(cases)} vaka)")

    # Domain dağılımı özeti
    from collections import Counter
    domains = Counter(c["expected_domain"] for c in cases)
    print("[*] Dağılım:")
    for d, n in domains.most_common():
        print(f"    {d:12s} {n:3d}")

    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
