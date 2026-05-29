"""BERT-TR fine-tune — dava sonucu tahmini (3-class). GPU'da koşar.

README §Fine-Tune Pipeline tasarımını uygular: dbmdz/bert-base-turkish-cased
+ 3-class head, HF Trainer, fp16, f1_macro best-model. Girdi: auto_label.py'nin
ürettiği leak-free JSONL (input_text=olay+gerekçe, label=hükümden).

Önkoşul (CPU'da hazırlanır): `uv run python -m scripts.predictive.auto_label`
Eğitim (GPU): `uv run python -m predictive.train --data data/predictive/labeled_v1.jsonl`

NOT: Bu modül torch/transformers'ı main() içinde import eder — `import predictive.train`
hafiftir (data_loader saf fonksiyonları GPU'suz test edilebilir).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Windows: pyarrow'u torch'tan ÖNCE yükle (transformers→datasets→pyarrow zinciri
# torch'tan sonra gelirse access-violation segfault → EXIT 139). native_preload.
from core import native_preload  # noqa: F401
from predictive.data_loader import (
    ID2LABEL,
    LABEL2ID,
    label_distribution,
    load_jsonl,
    stratified_split,
)

logger = logging.getLogger("predictive.train")

DEFAULT_MODEL = "dbmdz/bert-base-turkish-cased"


def compute_metrics(eval_pred: Any) -> dict[str, float]:
    """f1_macro + accuracy (README hedef: f1_macro ≥ 0.75)."""
    import numpy as np
    from sklearn.metrics import accuracy_score, f1_score

    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    return {
        "accuracy": float(accuracy_score(labels, preds)),
        "f1_macro": float(f1_score(labels, preds, average="macro")),
    }


def _build_training_args(out_dir: str, epochs: int, batch_size: int, lr: float, fp16: bool) -> Any:
    """README §Setup TrainingArguments — fp16 yalnız CUDA varsa."""
    from transformers import TrainingArguments

    return TrainingArguments(
        output_dir=out_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        learning_rate=lr,
        warmup_ratio=0.1,
        weight_decay=0.01,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1_macro",
        greater_is_better=True,
        fp16=fp16,
        gradient_checkpointing=True,
        logging_steps=50,
        report_to=[],
    )


def _run(args: argparse.Namespace) -> int:
    import torch
    from torch import nn
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
    )

    from predictive.data_loader import OutcomeDataset, compute_class_weights

    records = load_jsonl(args.data)
    if len(records) < 30:
        logger.error("yetersiz veri: %d kayıt (önce auto_label koş)", len(records))
        return 2
    logger.info("loaded %d kayıt | dağılım=%s", len(records), label_distribution(records))

    train_recs, val_recs, test_recs = stratified_split(
        records, val_frac=args.val_frac, test_frac=args.test_frac, seed=args.seed,
    )
    logger.info("split train=%d val=%d test=%d", len(train_recs), len(val_recs), len(test_recs))

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model,
        num_labels=len(LABEL2ID),
        problem_type="single_label_classification",
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    fp16 = torch.cuda.is_available() and not args.no_fp16
    training_args = _build_training_args(
        args.out_dir, args.epochs, args.batch_size, args.lr, fp16,
    )

    # Sınıf dengesizliği için ağırlıklı CE loss (kazandı az → f1_macro'yu korur).
    cw_map = compute_class_weights(train_recs)
    weights = torch.tensor(
        [cw_map.get(ID2LABEL[i], 1.0) for i in range(len(LABEL2ID))], dtype=torch.float,
    )
    logger.info("class_weights=%s", {ID2LABEL[i]: round(float(weights[i]), 3) for i in range(len(weights))})

    class WeightedTrainer(Trainer):
        """Ters-frekans sınıf ağırlıklı CE — dengesiz veride minority f1'i korur."""

        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None, **kwargs):
            # num_items_in_batch: transformers ≥4.46 explicit geçer (kwargs yutmasın).
            labels = inputs.get("labels")
            outputs = model(**{k: v for k, v in inputs.items() if k != "labels"})
            loss = nn.functional.cross_entropy(
                outputs.logits, labels, weight=weights.to(outputs.logits.device),
            )
            return (loss, outputs) if return_outputs else loss

    trainer = WeightedTrainer(
        model=model,
        args=training_args,
        train_dataset=OutcomeDataset(train_recs, tokenizer, args.max_length),
        eval_dataset=OutcomeDataset(val_recs, tokenizer, args.max_length),
        compute_metrics=compute_metrics,
    )

    logger.info("training_start fp16=%s device=%s", fp16, "cuda" if torch.cuda.is_available() else "cpu")
    trainer.train()

    # Holdout test (README §Splits: 1K test → final rapor)
    test_metrics = trainer.evaluate(OutcomeDataset(test_recs, tokenizer, args.max_length))
    logger.info("test_metrics=%s", test_metrics)

    best_dir = Path(args.out_dir) / "best"
    trainer.save_model(str(best_dir))
    tokenizer.save_pretrained(str(best_dir))

    metrics_path = Path(args.out_dir) / "metrics.json"
    metrics_path.write_text(json.dumps({
        "n_train": len(train_recs), "n_val": len(val_recs), "n_test": len(test_recs),
        "label_distribution": label_distribution(records),
        "test_metrics": {k: float(v) for k, v in test_metrics.items() if isinstance(v, int | float)},
        "model": args.model, "epochs": args.epochs, "lr": args.lr, "fp16": fp16,
        # Kalibrasyon'un AYNI veriyle koştuğunu doğrulamak için (calibrate_model guard).
        "data": Path(args.data).name,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("saved best→%s metrics→%s", best_dir, metrics_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="predictive.train")
    parser.add_argument("--data", default="data/predictive/labeled_v1.jsonl")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out-dir", default="predictive/checkpoints")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--val-frac", type=float, default=0.1)
    parser.add_argument("--test-frac", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-fp16", action="store_true", help="fp16 kapat (CPU/debug)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
