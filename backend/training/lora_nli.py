"""PEFT LoRA fine-tune — mDeBERTa XNLI NLI head, Türkçe sayısal-çıkarım için (anti-halüsinasyon FAZ 3.1).

KÖK SORUN: base mDeBERTa XNLI Türkçe sayısal/eşik çıkarımını NEUTRAL sayıyor (çelişki
recall ~%50). Bu modül base modeli LoRA ile DEVAM-eğitir (sıfırdan değil — 3-sınıf head
ve TR desteği korunur, catastrophic-forgetting riski düşük): sayısal-çıkarım çiftleri
(gen_nli_numeric) + genel TR-NLI örneklemi (nli_tr_gold) karışımı.

Entegrasyon: çıktı adapter `data/lora/nli-numeric/` → production `NLI_MODEL=<path>` env ile
verifier/nli.py yükler (PEFT adapter merge). layer3_nli_batch/eşik/cache AYNEN çalışır;
cache model-namespace ile auto-invalidate. Yeni eşik nli_tr_eval.threshold_sweep ile kalibre.

Default-safe: peft/datasets yoksa açıklayıcı ImportError (production runtime'a sızmaz;
yalnız `uv sync --extra lora`). 12GB GPU'ya sığar (mDeBERTa-base ~280MB + LoRA r=16).

Çalıştır (GPU boş olmalı — Qwen/embedder kapalı):
    uv run python -m training.lora_nli \\
        --numeric data/eval_benchmark/nli_numeric_train.jsonl \\
        --general data/eval_benchmark/nli_tr_gold.jsonl \\
        --output data/lora/nli-numeric --epochs 4
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

BASE_MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
# mDeBERTa XNLI id2label: 0=entailment, 1=neutral, 2=contradiction (verifier/nli.py ile AYNI).
_LABEL2ID = {"entailment": 0, "neutral": 1, "contradiction": 2}


def _load_pairs(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path or not path.exists():
        return rows
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("label") in _LABEL2ID and r.get("premise") and r.get("hypothesis"):
                rows.append(r)
    return rows


def _check_deps() -> None:
    try:
        import datasets  # noqa: F401
        import peft  # noqa: F401
        import transformers  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "lora_nli için training-extra gerekir: `uv sync --extra lora` "
            "(peft + datasets + transformers).",
        ) from exc


def train(args: argparse.Namespace) -> int:
    _check_deps()
    import numpy as np
    import torch
    from datasets import Dataset
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    rng = np.random.default_rng(args.seed)
    numeric = _load_pairs(args.numeric)
    general = _load_pairs(args.general)
    # Genel TR-NLI: catastrophic-forgetting önleme (sayısal-only fine-tune genel NLI'yı
    # bozmasın). Sayısalı baskın tut (kök-sorun) ama genel örneklemi koru.
    rows = numeric + general
    rng.shuffle(rows)
    print(f"[*] {len(numeric)} sayısal + {len(general)} genel = {len(rows)} çift")
    from collections import Counter
    print(f"    dağılım: {dict(Counter(r['label'] for r in rows))}")

    # Deterministik train/val (val = holdout, eşik kalibrasyonu DEV'de değil val'de değil
    # — nli_tr_eval ayrı holdout; bu val yalnız early-stop/loss izleme).
    n_val = max(4, int(len(rows) * args.val_split))
    val_rows, train_rows = rows[:n_val], rows[n_val:]

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)

    def _encode(batch: dict) -> dict:
        enc = tok(batch["premise"], batch["hypothesis"], truncation="only_first",
                  max_length=args.max_length, padding="max_length")
        enc["labels"] = [_LABEL2ID[x] for x in batch["label"]]
        return enc

    cols = ["premise", "hypothesis", "label"]
    train_ds = Dataset.from_list([{k: r[k] for k in cols} for r in train_rows]).map(
        _encode, batched=True, remove_columns=cols)
    val_ds = Dataset.from_list([{k: r[k] for k in cols} for r in val_rows]).map(
        _encode, batched=True, remove_columns=cols)

    model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL)
    lora = LoraConfig(
        task_type=TaskType.SEQ_CLS, r=args.r, lora_alpha=args.alpha,
        lora_dropout=args.dropout,
        # mDeBERTa-v2 attention proje katmanları (query/key/value).
        target_modules=["query_proj", "key_proj", "value_proj"],
        # classifier head'i de eğit (yoksa base XNLI head LoRA-değişen gövdeyle
        # uyumsuzlaşıp contradiction_recall=0 veriyordu — ilk deneme bulgusu).
        modules_to_save=["classifier", "pooler"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    def _metrics(eval_pred) -> dict:
        logits, labels = eval_pred
        preds = np.argmax(logits, axis=-1)
        acc = float((preds == labels).mean())
        # contradiction (id=2) recall — KÖK metrik (sayısal çelişki yakalama).
        con_mask = labels == 2
        con_recall = float((preds[con_mask] == 2).mean()) if con_mask.any() else 0.0
        return {"accuracy": acc, "contradiction_recall": con_recall}

    targs = TrainingArguments(
        output_dir=str(args.output / "_hf"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.lr,
        eval_strategy="epoch",
        save_strategy="no",
        logging_steps=10,
        # LoRA + fp16 "unscale FP16 gradients" hatası; bf16 (4070) çalışır ama DeBERTa-v3
        # disentangled-attention bf16'da kararsız olabilir → --fp32 ile tam-hassasiyet.
        bf16=(not args.fp32) and torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
        seed=args.seed,
        report_to=[],
    )
    trainer = Trainer(model=model, args=targs, train_dataset=train_ds,
                      eval_dataset=val_ds, compute_metrics=_metrics)
    trainer.train()
    final = trainer.evaluate()
    print(f"[*] val: acc={final.get('eval_accuracy'):.3f} "
          f"contradiction_recall={final.get('eval_contradiction_recall'):.3f}")

    args.output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(args.output))
    tok.save_pretrained(str(args.output))
    print(f"[OK] adapter → {args.output}")
    print(f"     Production: NLI_MODEL={args.output} (verifier/nli.py PEFT yükler)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--numeric", type=Path,
                    default=Path("data/eval_benchmark/nli_numeric_train.jsonl"))
    ap.add_argument("--general", type=Path,
                    default=Path("data/eval_benchmark/nli_tr_gold.jsonl"))
    ap.add_argument("--output", type=Path, default=Path("data/lora/nli-numeric"))
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--max-length", type=int, default=256)
    ap.add_argument("--val-split", type=float, default=0.15)
    ap.add_argument("--fp32", action="store_true", help="bf16 yerine fp32 (DeBERTa-v3 kararlılık)")
    ap.add_argument("--seed", type=int, default=42)
    return train(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
