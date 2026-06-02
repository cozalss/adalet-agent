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
import re
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


# --- Tam hüküm zenginleştirme (parquet join — hukum_excerpt yalnız 400-char kesitti) ---
_SHARDS = range(9)


# Disposition (sonuç bölümü) başlangıç işaretleri — Yargıtay kararı varyantları.
# "HÜKÜM:" / "SONUÇ:" + "VI. KARAR" / "Açıklanan (neden|sebep)..." gibi.
_DISPOSITION_RE = re.compile(
    r"(?i)\b(h[üu]k[üu]m\s*[:\.]|sonu[cç]\s*[:\.]|[ivx]{1,4}\s*[\.\-]\s*karar\b|"
    r"a[çc][ıi]klanan\s+(neden|sebep|gerek))",
)


def extract_full_hukum(text: str, cap: int = 3000) -> str:
    """Karar metninin SONUÇ (disposition) bölümü — temiz başlar, sonuna kadar tam.

    hukum_excerpt (auto_label) yalnız ilk 400 char + küçük-harf'ti → yarım. Bu:
    disposition marker'dan (HÜKÜM/SONUÇ/VI.KARAR/Açıklanan sebeplerle) sona kadar
    alır (orijinal case). Marker yoksa son `cap` karakter ama mid-cümle başlangıcı
    ilk '. ' sonrasına kırpılır (başı kesik 'l olacak...' görünmez). Disposition
    metnin SONUNDA olduğu için son daima korunur.
    """
    flat = " ".join(text.split())
    m = _DISPOSITION_RE.search(flat)
    seg = flat[m.start():] if m else flat
    if len(seg) > cap:
        seg = seg[-cap:]
        dot = seg.find(". ")
        if 0 <= dot < 600:           # mid-cümle başlangıcını temizle
            seg = seg[dot + 2:]
    return seg


def fetch_full_texts(needed_ids: set[str]) -> dict[str, str]:
    """Parquet shard'larını tara → {parquet_id: full_text} (yalnız gerekli id'ler, early-stop)."""
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    from scripts.seed_hf_yargitay import REPO

    found: dict[str, str] = {}
    for shard in _SHARDS:
        if len(found) >= len(needed_ids):
            break
        fp = hf_hub_download(repo_id=REPO, repo_type="dataset",
                             filename=f"data/train-{shard:05d}-of-00009.parquet")
        pf = pq.ParquetFile(fp)
        for batch in pf.iter_batches(batch_size=2000, columns=["id", "text"]):
            ids = batch.column("id").to_pylist()
            texts = batch.column("text").to_pylist()
            for did, txt in zip(ids, texts, strict=True):
                sid = str(did)
                if sid in needed_ids and sid not in found:
                    found[sid] = txt or ""
            if len(found) >= len(needed_ids):
                break
    return found


def enrich_candidates(candidates: list[dict]) -> int:
    """Her aday'a tam hüküm (`hukum_full`) ekle (parquet join). Eklenen sayısı döner."""
    needed = {c["doc_id"][2:] for c in candidates if c.get("doc_id", "").startswith("h-")}
    full = fetch_full_texts(needed)
    n = 0
    for c in candidates:
        txt = full.get(c.get("doc_id", "")[2:])
        if txt:
            c["hukum_full"] = extract_full_hukum(txt)
            n += 1
    return n


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
        ChatMessage(role="user", content=f"OLAY ÖZETİ:\n{facts[:600]}\n\nHÜKÜM:\n{hukum[:1800]}"),
    ]
    resp = await llm.chat(msgs, temperature=0.0, max_tokens=160, json_mode=True)
    return parse_adjudication(resp.content)


async def run(n: int) -> None:
    records = load_jsonl(_DATA)
    _train, _val, test = stratified_split(records, seed=42)  # held-out test (modelin görmediği)
    sample = _sample(test, n)
    # TAM hükmü parquet'ten çek (hukum_excerpt yalnız 400-char kesit → Qwen yarım okurdu).
    print(f"[*] {len(sample)} vaka — tam hüküm parquet'ten çekiliyor...", flush=True)
    full = fetch_full_texts({r["doc_id"][2:] for r in sample
                             if r.get("doc_id", "").startswith("h-")})
    print(f"[*] {len(full)}/{len(sample)} tam metin bulundu; Qwen adjudication (tam hüküm)...",
          flush=True)

    llm = get_llm()
    candidates: list[dict] = []
    pairs: list[tuple[str, str]] = []
    n_fail = 0
    for i, r in enumerate(sample):
        full_text = full.get(r.get("doc_id", "")[2:], "")
        hukum_full = extract_full_hukum(full_text) if full_text else str(r.get("hukum_excerpt", ""))
        try:
            res = await _adjudicate(llm, r.get("input_text", ""), hukum_full)
        except Exception as exc:  # bir vaka LLM hatası tüm koşuyu öldürmesin
            n_fail += 1
            print(f"    [!] {i} adjudication hatası ({type(exc).__name__}), atlanıyor", flush=True)
            res = None
        if res is None:
            continue
        qwen_label, quote = res
        pairs.append((r["label"], qwen_label))
        candidates.append({
            "doc_id": r.get("doc_id", ""),
            "input_text": r["input_text"],
            "hukum_excerpt": r.get("hukum_excerpt", ""),
            "hukum_full": hukum_full,  # TAM hüküm (hukukçu + Qwen bunu okur)
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
    print(f"\n{bar}\n  GOLD-ADAY İNŞASI — {len(candidates)} vaka "
          f"(LLM-adjudicated, {n_fail} LLM hatası atlandı)\n{bar}")
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
