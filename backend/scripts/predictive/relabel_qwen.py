"""Faz-5 düzeltme — Qwen TAM-HÜKÜM ile yeniden etiketle (silver onama/bozma'da yanlıştı).

Silver `_classify_outcome` regex'i 400-char kesitten + onama/bozma karmaşasıyla rastgele-altı
etiket üretiyordu (BERT 0.825 silver'da ama tam-hüküm Qwen-ref'inde 0.28). Çözüm: aynı leak-free
girdi (input_text = olay+gerekçe, hüküm HARİÇ) için Qwen'in TAM HÜKÜM okumasını DOĞRU etiket olarak
kullan → BERT bu doğru eşlemeyi öğrensin.

Kaynak: labeled_v2'nin TRAIN-split'i (seed=42) — gold_qwen test-split'iyle ÇAKIŞMAZ (temiz eval).
Incremental save (her satır flush) → uzun koşu çökerse ilerleme korunur. LLM_SPECULATIVE=0 önerilir
(uzun-prompt logits çökme guard'ı). 'belirsiz' + LLM-hatası atlanır.

Kullanım (yerel LLM, ~saatler):
  cd backend && LLM_MODE=llamacpp LLM_SPECULATIVE=0 \
    LLM_MODEL_PATH=./models/Qwen2.5-14B-Instruct-Q5_K_M.gguf \
    uv run python -m scripts.predictive.relabel_qwen --n 3000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

# Windows: pyarrow'u torch'tan ÖNCE yükle (datasets/torch segfault guard).
from core import native_preload  # noqa: F401
from predictive.data_loader import LABEL2ID, load_jsonl, stratified_split
from scripts.predictive.build_gold_eval import (
    _adjudicate,
    extract_full_hukum,
    fetch_full_texts,
)

_DATA = "data/predictive/labeled_v2.jsonl"
_OUT = Path("data/predictive/labeled_qwen.jsonl")


async def run(n: int, out_path: Path) -> None:
    records = load_jsonl(_DATA)
    train, val, _test = stratified_split(records, seed=42)  # _test = gold_qwen kaynağı (HARİÇ)
    pool = train + val
    rng = random.Random(123)
    rng.shuffle(pool)
    sample = pool[:n]

    print(f"[*] {len(sample)} vaka (train+val pool) — tam hüküm parquet'ten çekiliyor...", flush=True)
    full = fetch_full_texts({r["doc_id"][2:] for r in sample if r.get("doc_id", "").startswith("h-")})
    print(f"[*] {len(full)}/{len(sample)} tam metin; Qwen yeniden-etiketleme başlıyor...", flush=True)

    from agents.llm import get_llm
    llm = get_llm()
    n_written = n_fail = n_belirsiz = 0
    dist: dict[str, int] = {}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for i, r in enumerate(sample):
            ft = full.get(r.get("doc_id", "")[2:], "")
            hukum = extract_full_hukum(ft) if ft else str(r.get("hukum_excerpt", ""))
            try:
                res = await _adjudicate(llm, r.get("input_text", ""), hukum)
            except Exception:  # bir vaka LLM hatası koşuyu öldürmesin
                n_fail += 1
                res = None
            if res is None:
                continue
            label, _quote = res
            if label not in LABEL2ID:  # 'belirsiz' → eğitime girmez (3-class)
                n_belirsiz += 1
                continue
            f.write(json.dumps({
                "doc_id": r.get("doc_id", ""), "chamber": r.get("chamber", ""),
                "domain": r.get("domain", ""), "input_text": r["input_text"],
                "label": label,
            }, ensure_ascii=False) + "\n")
            f.flush()  # incremental — uzun koşu çökerse ilerleme korunur
            n_written += 1
            dist[label] = dist.get(label, 0) + 1
            if (i + 1) % 50 == 0:
                print(f"    {i+1}/{len(sample)} yazılan={n_written} dağılım={dist} "
                      f"(belirsiz={n_belirsiz} hata={n_fail})", flush=True)

    print(f"[+] {n_written} Qwen-etiketli -> {out_path}")
    print(f"    dağılım={dist} | belirsiz={n_belirsiz} | LLM-hata={n_fail}")
    print(f"    Eğit: uv run python -m predictive.train --data {out_path}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import os
    if os.getenv("LLM_MODE", "mock") == "mock":
        print("[!] LLM_MODE=mock — gerçek için LLM_MODE=llamacpp (+ LLM_SPECULATIVE=0).", flush=True)
    parser = argparse.ArgumentParser(description="Qwen tam-hüküm ile yeniden etiketle")
    parser.add_argument("--n", type=int, default=3000, help="Yeniden etiketlenecek vaka sayısı")
    parser.add_argument("--out", default=str(_OUT))
    args = parser.parse_args()
    asyncio.run(run(args.n, Path(args.out)))


if __name__ == "__main__":
    main()
