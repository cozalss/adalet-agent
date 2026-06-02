"""DistilBERT-TR domain triaj sınıflandırıcısı — fine-tune (HF Trainer).

data/triage/{train,val}.jsonl üzerinde `dbmdz/distilbert-base-turkish-cased`'i
8 sivil domain için ince-ayarlar; çıktıyı models/triage-distilbert'e kaydeder
(config.label2id/id2label TRIAGE_LABELS ile birebir — inference bu indekslemeye bağlı).

Bu script KULLANICININ GPU'sunda koşar (predictive/train.py deseni). Çıktı dizini
oluşunca agents/triage_classifier.py modeli otomatik kullanır (TRIAGE_USE_MODEL=1).

Kullanım:
    cd backend
    uv run python -m scripts.triage.gen_data          # veriyi üret (bir kez)
    uv run python -m scripts.triage.train             # fine-tune (GPU önerilir)
    # → models/triage-distilbert/ (tokenizer + model + config)
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.triage_classifier import TRIAGE_LABELS

_BASE_MODEL = "dbmdz/distilbert-base-turkish-cased"
_OUT_DIR = "models/triage-distilbert"
_MAX_LEN = 128
_EPOCHS = 4
_BATCH = 16
_LR = 3e-5

LABEL2ID = {label: i for i, label in enumerate(TRIAGE_LABELS)}
ID2LABEL = dict(enumerate(TRIAGE_LABELS))


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    import numpy as np
    from datasets import Dataset
    from sklearn.metrics import accuracy_score, f1_score
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
    )

    data_dir = Path("data/triage")
    train_rows = _load_jsonl(data_dir / "train.jsonl")
    val_rows = _load_jsonl(data_dir / "val.jsonl")
    print(f"  train={len(train_rows)} val={len(val_rows)} | {len(TRIAGE_LABELS)} domain")

    tok = AutoTokenizer.from_pretrained(_BASE_MODEL)

    def _prep(rows: list[dict]) -> Dataset:
        ds = Dataset.from_list([
            {"text": r["text"], "labels": LABEL2ID[r["label"]]} for r in rows
        ])
        return ds.map(
            lambda b: tok(b["text"], truncation=True, max_length=_MAX_LEN),
            batched=True, remove_columns=["text"],
        )

    train_ds, val_ds = _prep(train_rows), _prep(val_rows)

    model = AutoModelForSequenceClassification.from_pretrained(
        _BASE_MODEL, num_labels=len(TRIAGE_LABELS), id2label=ID2LABEL, label2id=LABEL2ID,
    )

    def _metrics(eval_pred) -> dict:
        logits, labels = eval_pred
        preds = np.argmax(logits, axis=-1)
        return {
            "accuracy": accuracy_score(labels, preds),
            "f1_macro": f1_score(labels, preds, average="macro"),
        }

    args = TrainingArguments(
        output_dir=_OUT_DIR + "-ckpt",
        num_train_epochs=_EPOCHS,
        per_device_train_batch_size=_BATCH,
        per_device_eval_batch_size=_BATCH,
        learning_rate=_LR,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1_macro",
        logging_steps=20,
        report_to=[],
    )
    trainer = Trainer(
        model=model, args=args, train_dataset=train_ds, eval_dataset=val_ds,
        data_collator=DataCollatorWithPadding(tok), compute_metrics=_metrics,
    )
    trainer.train()
    metrics = trainer.evaluate()
    print(f"  val: accuracy={metrics['eval_accuracy']:.4f} f1_macro={metrics['eval_f1_macro']:.4f}")

    out = Path(_OUT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    trainer.save_model(out)
    tok.save_pretrained(out)
    print(f"  model -> {out}  (agents/triage_classifier.py otomatik kullanır)")


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
