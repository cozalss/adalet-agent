"""Faz-4 adım 4 — Türkçe-hukuk cross-encoder reranker fine-tune (GPU adımı).

data/reranker/{train,val}.jsonl ({query, passage, label}) üzerinde bir cross-encoder'ı
fine-tune eder. Warm-start varsayılanı projenin mevcut reranker'ı (BAAI/bge-reranker-v2-m3)
→ çıktı DROP-IN yedek (RERANKER_MODEL env'ini yerel yola çevirince üretim kullanır).
Daha güçlü TR başlangıç için --warm-start seroe/bge-reranker-v2-m3-turkish-triplet
(telekom-tuned ama TR cross-encoder; hukuk verimizle RE-fine-tune edilir).

ST5 modern API: CrossEncoderTrainer + BinaryCrossEntropyLoss (etiketli-çift). Mevcut
predictive/triage train deseni: model→models/ dizinine, env ile üretime bağlanır.

Kullanım (GPU): cd backend && uv run python -m scripts.reranker.train
  → models/reranker-tr-legal/    (üretim: RERANKER_MODEL=models/reranker-tr-legal)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows: pyarrow'u torch'tan ÖNCE yükle (transformers/datasets segfault guard).
from core import native_preload  # noqa: F401

_DIR = Path("data/reranker")
_DEFAULT_WARM_START = "BAAI/bge-reranker-v2-m3"  # proje reranker'ı — drop-in yedek
_OUT_DIR = "models/reranker-tr-legal"


def _load_split(name: str):
    from datasets import load_dataset

    path = _DIR / f"{name}.jsonl"
    if not path.exists():
        raise SystemExit(f"{path} yok — önce mine_negatives çalıştır.")
    return load_dataset("json", data_files=str(path), split="train")


def train(warm_start: str, out_dir: str, epochs: int, batch_size: int,
          lr: float) -> None:
    from sentence_transformers import CrossEncoder
    from sentence_transformers.cross_encoder import (
        CrossEncoderTrainer,
        CrossEncoderTrainingArguments,
    )
    from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss

    train_ds = _load_split("train")
    eval_ds = _load_split("val")
    print(f"[*] train {len(train_ds)} / val {len(eval_ds)} | warm-start: {warm_start}",
          flush=True)

    model = CrossEncoder(warm_start, num_labels=1)
    loss = BinaryCrossEntropyLoss(model)
    args = CrossEncoderTrainingArguments(
        output_dir=f"{out_dir}-ckpt",
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        learning_rate=lr,
        warmup_ratio=0.1,
        fp16=True,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        logging_steps=20,
        load_best_model_at_end=True,
        report_to=[],
    )
    trainer = CrossEncoderTrainer(
        model=model, args=args,
        train_dataset=train_ds, eval_dataset=eval_ds, loss=loss,
    )
    trainer.train()
    model.save_pretrained(out_dir)
    print(f"[+] Model kaydedildi -> {out_dir}")
    print(f"    Üretime bağla: RERANKER_MODEL={out_dir} (retrieval/reranker.py otomatik kullanır)")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="TR-hukuk cross-encoder reranker fine-tune")
    parser.add_argument("--warm-start", default=_DEFAULT_WARM_START,
                        help="Başlangıç checkpoint (varsayılan proje reranker'ı)")
    parser.add_argument("--out", default=_OUT_DIR)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    args = parser.parse_args()
    train(args.warm_start, args.out, args.epochs, args.batch_size, args.lr)


if __name__ == "__main__":
    main()
