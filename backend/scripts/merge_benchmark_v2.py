"""Merge benchmark.jsonl + benchmark_v2_generated.jsonl → benchmark_v2.jsonl.

Sprint-4 W2.2. Adımlar:
    1. Mevcut 50 vakayı oku (benchmark.jsonl), `source: legacy` etiketle
    2. Yeni programmatic vakaları oku (benchmark_v2_generated.jsonl)
    3. Duplicate filtrele (soru lowercased exact eşleşme)
    4. ID re-seq: V_{domain}_{NNN} formatına çevir (versiyon tutarlılığı)
    5. Domain dağılımı raporu
    6. benchmark_v2.jsonl olarak yaz

Çalıştırma:
    uv run python -m scripts.merge_benchmark_v2

NOT: benchmark.jsonl orijinal halinde bozulmaz (W2 ablation karşılaştırmaları
için geri uyumluluk). benchmark_v2.jsonl yeni varsayılan olur — freeze_baseline
script'i --benchmark v2 ile yeni dosyayı seçebilir.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
BASE_PATH = REPO_ROOT / "data" / "eval_benchmark" / "benchmark.jsonl"
GENERATED_PATH = REPO_ROOT / "data" / "eval_benchmark" / "benchmark_v2_generated.jsonl"
OUT_PATH = REPO_ROOT / "data" / "eval_benchmark" / "benchmark_v2.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Boş satırları skip ederek JSONL oku."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _normalize_question(q: str) -> str:
    """Dedup için soru normalize — lowercase, ws-collapse, noktalama temizle."""
    import re as _re
    norm = q.lower().strip()
    norm = _re.sub(r"[?.!,;:]+", " ", norm)
    norm = _re.sub(r"\s+", " ", norm)
    return norm.strip()


def _dedup(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aynı normalize'lı soru → ilk geleni tut, sonrakileri at.

    Legacy vakalar önce gelir (öncelik) çünkü bunlar manuel etiketli ve daha
    güvenilir keyword/madde_no içerir.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for c in cases:
        key = _normalize_question(c.get("soru", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _reseq_ids(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ID'leri V_{domain}_{NNN} formatına çevir (domain başına sayaç)."""
    counters: defaultdict[str, int] = defaultdict(int)
    for c in cases:
        dom = c.get("expected_domain", "unknown")
        counters[dom] += 1
        c["id"] = f"V_{dom}_{counters[dom]:03d}"
    return cases


def _report(cases: list[dict[str, Any]]) -> None:
    """Stdout'a dağılım raporu."""
    if not cases:
        print("[!] Hiç vaka yok — boş çıktı.")
        return

    print(f"\nToplam: {len(cases)} vaka")
    print()

    by_domain = Counter(c["expected_domain"] for c in cases)
    print("Domain dağılımı:")
    for d, n in by_domain.most_common():
        print(f"  {d:12s} {n:3d}")

    by_source = Counter(c.get("source", "legacy") for c in cases)
    print("\nKaynak dağılımı:")
    for s, n in by_source.most_common():
        print(f"  {s:20s} {n:3d}")

    kanun_dist = Counter(k for c in cases for k in c.get("expected_kanun", []))
    print("\nExpected kanun (top 10):")
    for k, n in kanun_dist.most_common(10):
        print(f"  {k:10s} {n:3d}")


def main() -> int:
    legacy = _read_jsonl(BASE_PATH)
    generated = _read_jsonl(GENERATED_PATH)

    print(f"[*] Legacy benchmark.jsonl: {len(legacy)} vaka")
    print(f"[*] Programmatic v2:       {len(generated)} vaka")

    # Legacy vakalarına source etiketle (boşsa)
    for c in legacy:
        c.setdefault("source", "legacy")

    merged = legacy + generated
    deduped = _dedup(merged)
    print(f"[*] Merge sonrası dedup:   {len(deduped)} vaka "
          f"({len(merged) - len(deduped)} duplicate atıldı)")

    reseq = _reseq_ids(deduped)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for c in reseq:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\n[OK] Yazıldı: {OUT_PATH}")
    _report(reseq)
    return 0


if __name__ == "__main__":
    sys.exit(main())
