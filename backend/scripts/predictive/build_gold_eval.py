"""Faz-5 GOLD eval-set inşası — LLM-adjudicated referans + insan-incelemeye hazır.

Silver etiket (auto_label regex'i ~%70) modelin GERÇEK doğruluğunu ölçemez. Bu script
held-out test-split'ten stratifiye örnek alır ve her kararın HÜKÜM bölümünü yerel Qwen'e
OKUTUP (davacı açısından sonuç; onama/bozma dahil) daha yüksek-kaliteli bir referans üretir.

DÜRÜSTLÜK (CLAUDE.md §1): Bu İNSAN-doğrulanmış değil, LLM-ADJUDICATED'dır — Qwen yalnız
metinde YAZILI sonucu okur (uydurma yok), ama hâlâ hata yapabilir. Çıktıda `human_label`
sütunu BOŞ bırakılır → hukuk öğrencisi 1-2 saatte kesinleştirir; sonra `eval_predict --gold`
gerçek insan-doğrulanmış doğruluğu verir. Şimdilik Qwen-referansı silver'dan iyi bir köprüdür.

Üretir:
  data/predictive/gold_candidates.jsonl  — {doc_id, input_text, hukum_excerpt, silver_label,
                                            qwen_label, quote, needs_review, human_label:""}
  data/predictive/gold_qwen.jsonl        — {input_text, label:qwen_label}  (eval_predict --gold)

Kullanım (yerel LLM):
  cd backend && LLM_MODE=llamacpp LLM_MODEL_PATH=./models/Qwen2.5-14B-Instruct-Q5_K_M.gguf \
    uv run python -m scripts.predictive.build_gold_eval --n 150
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

from agents.llm import ChatMessage, get_llm

# Windows: pyarrow'u torch'tan ÖNCE yükle (datasets/torch segfault guard).
from core import native_preload  # noqa: F401
from predictive.data_loader import LABEL2ID, load_jsonl, stratified_split

_DATA = "data/predictive/labeled_v2.jsonl"
_OUT_DIR = Path("data/predictive")
_VALID = {"kazandi", "kaybetti", "kismi", "belirsiz"}

_ADJUDICATE_SYSTEM = (
    "Sen deneyimli bir Türk hukuk uzmanısın. Sana bir Yargıtay kararının olay özeti + "
    "HÜKÜM bölümü verilecek. DAVACI (talebi öne süren taraf) açısından sonucu sınıflandır:\n"
    "- kazandi: davacının davası/talebi kabul edildi VEYA aleyhindeki karar BOZULDU (lehe döndü)\n"
    "- kaybetti: davacının davası/talebi reddedildi VEYA ret kararı ONANDI (aleyhe kesinleşti)\n"
    "- kismi: kısmen kabul / kısmen ret\n"
    "- belirsiz: hükümden davacı açısından sonuç NET çıkarılamıyor\n"
    "KURALLAR: (1) Yalnız metinde YAZILI olanı oku; dışarıdan bilgi/tahmin EKLEME. "
    "(2) Onama = alt mahkeme kararı aynen geçerli; Bozma = alt mahkeme kararı geçersiz. "
    "(3) Emin değilsen 'belirsiz' de. "
    'Yanıtı SADECE JSON ver: {"label": "...", "quote": "<sonucu belirten kısa cümle>"}'
)


def parse_adjudication(raw: str) -> tuple[str, str] | None:
    """Qwen JSON çıktısını (label, quote)'a indir; geçersiz label → None. Saf, test'li."""
    if not raw:
        return None
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    label = str(obj.get("label", "")).strip().lower()
    if label not in _VALID:
        return None
    return label, str(obj.get("quote", "")).strip()


def agreement_stats(pairs: list[tuple[str, str]]) -> dict:
    """(silver, qwen) çiftlerinden genel + silver-sınıfı-başına uyum oranı. Saf."""
    if not pairs:
        return {"n": 0, "overall": 0.0, "per_silver": {}}
    overall = sum(1 for s, q in pairs if s == q) / len(pairs)
    per: dict[str, dict] = {}
    for label in sorted({s for s, _ in pairs}):
        grp = [(s, q) for s, q in pairs if s == label]
        per[label] = {"n": len(grp), "agree": round(sum(1 for s, q in grp if s == q) / len(grp), 3)}
    return {"n": len(pairs), "overall": round(overall, 3), "per_silver": per}


def _sample(records: list[dict], n: int, seed: int = 7) -> list[dict]:
    """Silver-sınıfı stratifiye örnek (her sınıftan ~n/3)."""
    by: dict[str, list[dict]] = {}
    for r in records:
        by.setdefault(r["label"], []).append(r)
    rng = random.Random(seed)
    per_class = max(1, n // len(by))
    out: list[dict] = []
    for label in sorted(by):
        grp = by[label][:]
        rng.shuffle(grp)
        out.extend(grp[:per_class])
    rng.shuffle(out)
    return out


async def _adjudicate(llm, facts: str, hukum: str) -> tuple[str, str] | None:
    msgs = [
        ChatMessage(role="system", content=_ADJUDICATE_SYSTEM),
        ChatMessage(role="user", content=f"OLAY ÖZETİ:\n{facts[:500]}\n\nHÜKÜM:\n{hukum[:600]}"),
    ]
    resp = await llm.chat(msgs, temperature=0.0, max_tokens=160, json_mode=True)
    return parse_adjudication(resp.content)


async def run(n: int) -> None:
    records = load_jsonl(_DATA)
    _train, _val, test = stratified_split(records, seed=42)  # held-out test (modelin görmediği)
    sample = _sample(test, n)
    print(f"[*] {len(sample)} held-out vaka Qwen ile adjudicate ediliyor...", flush=True)

    llm = get_llm()
    candidates: list[dict] = []
    pairs: list[tuple[str, str]] = []
    for i, r in enumerate(sample):
        res = await _adjudicate(llm, r.get("input_text", ""), str(r.get("hukum_excerpt", "")))
        if res is None:
            continue
        qwen_label, quote = res
        pairs.append((r["label"], qwen_label))
        candidates.append({
            "doc_id": r.get("doc_id", ""),
            "input_text": r["input_text"],
            "hukum_excerpt": r.get("hukum_excerpt", ""),
            "silver_label": r["label"],
            "qwen_label": qwen_label,
            "quote": quote,
            "needs_review": r["label"] != qwen_label,
            "human_label": "",  # ← hukuk öğrencisi doldurur (gerçek GOLD)
        })
        if (i + 1) % 20 == 0:
            print(f"    {i+1}/{len(sample)}", flush=True)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    cand_path = _OUT_DIR / "gold_candidates.jsonl"
    with cand_path.open("w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    # Qwen-referans eval seti (eval_predict --gold ile ölçülür; qwen_label != belirsiz)
    qwen_path = _OUT_DIR / "gold_qwen.jsonl"
    with qwen_path.open("w", encoding="utf-8") as f:
        for c in candidates:
            if c["qwen_label"] in LABEL2ID:  # belirsiz hariç (3-class eval)
                f.write(json.dumps({"input_text": c["input_text"], "label": c["qwen_label"]},
                                   ensure_ascii=False) + "\n")

    stats = agreement_stats(pairs)
    bar = "=" * 60
    print(f"\n{bar}\n  GOLD-ADAY İNŞASI — {len(candidates)} vaka (LLM-adjudicated)\n{bar}")
    print(f"  silver↔qwen genel uyum = {stats['overall']:.1%}  → silver kalitesi ~bu")
    for lab, m in stats["per_silver"].items():
        print(f"    silver={lab:<10} n={m['n']:<4} qwen-uyum={m['agree']:.1%}")
    n_review = sum(1 for c in candidates if c["needs_review"])
    n_belirsiz = sum(1 for c in candidates if c["qwen_label"] == "belirsiz")
    print(f"  {'-'*58}")
    print(f"  insan-incelemesi gereken (silver≠qwen) = {n_review}/{len(candidates)}")
    print(f"  qwen 'belirsiz' = {n_belirsiz} (3-class eval'den çıkar)")
    print(f"  -> {cand_path}  (human_label doldur)")
    print(f"  -> {qwen_path}  (uv run python -m predictive.eval_predict --gold {qwen_path})")
    print(bar)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import os
    if os.getenv("LLM_MODE", "mock") == "mock":
        print("[!] LLM_MODE=mock — gerçek adjudication için LLM_MODE=llamacpp gerekir.", flush=True)
    parser = argparse.ArgumentParser(description="GOLD eval-set inşası (LLM-adjudicated)")
    parser.add_argument("--n", type=int, default=150, help="Adjudicate edilecek vaka sayısı")
    args = parser.parse_args()
    asyncio.run(run(args.n))


if __name__ == "__main__":
    main()
