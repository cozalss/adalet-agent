"""Benchmark gold doğrulayıcı — her (kanun, madde) çifti corpus'ta VAR MI? (P6, 2026-06-10)

Gold'daki yanlış kanun kodu / olmayan madde numarası o vakayı kalıcı-miss yapar ve
metriği sessizce aşağı çeker (bulundu: V_idari_009 IYUK m.125 — İYUK'ta 125. madde
YOK, doğrusu DMK 125). Bu araç eval'den bağımsız, Qdrant'a filtre-count ile bakar:

    uv run python -m scripts.validate_benchmark_gold                 # v2 (default)
    uv run python -m scripts.validate_benchmark_gold --file data/eval_benchmark/benchmark_v3_ext.jsonl

Çıkış kodu: 0 = hepsi geçerli, 1 = geçersiz gold var (CI'da kullanılabilir).
NOT: yalnız VARLIK doğrular; 'semantik olarak doğru madde mi' insan işi.
Ek/Geçici madde gold'ları ('ek-1' gibi str) corpus'ta hiç yok (bilinen P8 boşluğu)
→ '--allow-ek' verilmedikçe uyarı sayılır ama hata sayılmaz (zaten eval dışı).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import native_preload  # noqa: F401

logger = logging.getLogger("validate_gold")
DEFAULT_PATH = Path(__file__).parent.parent / "data" / "eval_benchmark" / "benchmark_v2.jsonl"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1254 konsolu

    import os

    from qdrant_client import AsyncQdrantClient, models

    collection = os.getenv("QDRANT_COLLECTION", "adalet_mursit_hybrid")
    client = AsyncQdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))

    cases = []
    with args.file.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                cases.append(json.loads(line))
    print(f"Dosya: {args.file} — {len(cases)} vaka, koleksiyon: {collection}\n")

    # Tekil (kanun, madde) çiftleri — aynı çifti bir kez sorgula.
    pairs: set[tuple[str, int]] = set()
    ek_golds: list[tuple[str, str]] = []
    for c in cases:
        for kanun in c.get("expected_kanun", []):
            for m in c.get("expected_madde_no", []):
                if str(m).strip().lstrip("-").isdigit():
                    pairs.add((kanun, int(m)))
                else:
                    ek_golds.append((c["id"], f"{kanun} m.{m}"))

    missing: list[tuple[str, int]] = []
    for kanun, madde in sorted(pairs):
        flt = models.Filter(must=[
            models.FieldCondition(key="kanun_kodu", match=models.MatchValue(value=kanun)),
            models.FieldCondition(key="madde_no", match=models.MatchValue(value=madde)),
            models.FieldCondition(key="doc_type", match=models.MatchValue(value="law")),
        ])
        n = (await client.count(collection, count_filter=flt, exact=True)).count
        if n == 0:
            missing.append((kanun, madde))
    await client.close()

    if ek_golds:
        print(f"UYARI — Ek/Geçici madde gold'u ({len(ek_golds)}; P8 boşluğu, eval-dışı):")
        for cid, ref in ek_golds:
            print(f"  {cid}: {ref}")
        print()

    if not missing:
        print(f"TAMAM — {len(pairs)} tekil (kanun, madde) çiftinin hepsi corpus'ta mevcut.")
        return 0

    print(f"GEÇERSİZ GOLD — {len(missing)}/{len(pairs)} çift corpus'ta YOK:")
    bad_pairs = set(missing)
    for kanun, madde in missing:
        sahipler = [c["id"] for c in cases
                    if kanun in c.get("expected_kanun", [])
                    and any(str(m).isdigit() and int(m) == madde
                            for m in c.get("expected_madde_no", []))]
        print(f"  {kanun} m.{madde}  <- {', '.join(sahipler)}")
    _ = bad_pairs
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
