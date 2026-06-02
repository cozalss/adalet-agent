"""Faz-4 adım 3 — hard-negative madenle + nihai eğitim seti (train/val) montajı.

(sorgu, pozitif) çiftlerinin (resmî + sentez) 3. ayağını — İLGİSİZ ama YAKIN aday —
sentence_transformers.util.mine_hard_negatives ile dataset corpus'undan madenler.
Embedder (Mursit-Base-TR, gerçek SentenceTransformer) ile pozitif-pool'dan top-benzer
negatifleri çeker; opsiyonel cross-encoder yeniden-skorla yanlış-negatifleri (aslında
ilgili adayı) ELER (margin). Çıktı CrossEncoder eğitimi için etiketli-çift.

KIRMIZI ÇİZGİ: tüm metinler GERÇEK kararlardan (corpus.jsonl); negatif = gerçek başka
bir karar/madde, uydurma değil.

Üretir:
  data/reranker/train.jsonl  / val.jsonl  — {"query","passage","label"}  (label 1.0/0.0)

Kullanım: cd backend && uv run python -m scripts.reranker.mine_negatives [--num-negatives 4] [--cross-encoder]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows: pyarrow'u torch'tan ÖNCE yükle (SentenceTransformer + datasets segfault guard).
from core import native_preload  # noqa: F401
from scripts.reranker._core import QAPair, dedup_pairs, split_train_val

_DIR = Path("data/reranker")
# Hazır TR-hukuk dense embedder (newmindai, Apache-2.0) — madenleme retriever'ı.
_MINE_MODEL = "newmindai/Mursit-Base-TR-Retrieval"
_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _combined_pairs() -> list[QAPair]:
    """Resmî (pairs.jsonl) + sentez (synth_pairs.jsonl) çiftlerini birleştir + dedup."""
    rows = _load_jsonl(_DIR / "pairs.jsonl") + _load_jsonl(_DIR / "synth_pairs.jsonl")
    pairs = [QAPair(**r) for r in rows]
    return dedup_pairs(pairs)


def _normalize_labeled(ds) -> list[dict]:
    """mine_hard_negatives 'labeled-pair' çıktısını {query,passage,label}'a indir.

    Kolon adları ST sürümüne göre değişebilir (anchor/query, positive/passage); label
    sayısal kolondur. Konuma göre sağlam eşle: [metin1=query, metin2=passage, label].
    """
    cols = ds.column_names
    label_col = next((c for c in cols if "label" in c.lower()
                      or ds.features[c].dtype in ("float32", "float64", "int64")), cols[-1])
    text_cols = [c for c in cols if c != label_col]
    q_col, p_col = text_cols[0], text_cols[1]
    return [{"query": r[q_col], "passage": r[p_col], "label": float(r[label_col])}
            for r in ds]


def mine(num_negatives: int, margin: float, range_min: int,
         use_cross_encoder: bool, batch_size: int, use_faiss: bool = False) -> list[dict]:
    """Hard-negative madenle → etiketli-çift kayıt listesi."""
    from datasets import Dataset
    from sentence_transformers import CrossEncoder, SentenceTransformer
    from sentence_transformers.util import mine_hard_negatives

    pairs = _combined_pairs()
    if not pairs:
        raise SystemExit("data/reranker/pairs.jsonl yok — önce load_sources çalıştır.")
    corpus_texts = [c["text"] for c in _load_jsonl(_DIR / "corpus.jsonl")]

    ds = Dataset.from_dict({
        "anchor": [p.query for p in pairs],
        "positive": [p.pos_text for p in pairs],
    })
    print(f"[*] {len(pairs)} çift, {len(corpus_texts)} corpus belgesi; embedder yükleniyor...",
          flush=True)
    model = SentenceTransformer(_MINE_MODEL)
    cross_encoder = CrossEncoder(_RERANKER_MODEL) if use_cross_encoder else None

    mined = mine_hard_negatives(
        ds, model,
        corpus=corpus_texts or None,
        cross_encoder=cross_encoder,
        num_negatives=num_negatives,
        range_min=range_min,        # ilk N en-benzeri atla (muhtemel yanlış-negatif)
        absolute_margin=margin,     # pozitif skoru - negatif skoru >= margin (ST5 API)
        sampling_strategy="top",
        output_format="labeled-pair",
        batch_size=batch_size,
        use_faiss=use_faiss,
        verbose=True,
    )
    return _normalize_labeled(mined)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Hard-negative madenleme → train/val")
    parser.add_argument("--num-negatives", type=int, default=4)
    parser.add_argument("--margin", type=float, default=0.05,
                        help="Pozitif-negatif skor marjı (yanlış-negatif eler)")
    parser.add_argument("--range-min", type=int, default=10,
                        help="İlk N en-benzeri negatif sayma (yanlış-negatif guard)")
    parser.add_argument("--cross-encoder", action="store_true",
                        help="bge-reranker ile yeniden-skorla (daha kaliteli, daha yavaş)")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--val-frac", type=float, default=0.1)
    parser.add_argument("--faiss", action="store_true",
                        help="FAISS ile ANN ara (faiss kuruluysa; varsayılan torch)")
    args = parser.parse_args()

    rows = mine(args.num_negatives, args.margin, args.range_min,
                args.cross_encoder, args.batch_size, args.faiss)
    train, val = split_train_val(rows, val_frac=args.val_frac)
    _write_jsonl(_DIR / "train.jsonl", train)
    _write_jsonl(_DIR / "val.jsonl", val)
    pos = sum(1 for r in rows if r["label"] >= 0.5)
    print(f"[+] {len(rows)} etiketli-çift ({pos} pozitif / {len(rows)-pos} negatif) "
          f"-> train {len(train)} / val {len(val)}")


if __name__ == "__main__":
    main()
