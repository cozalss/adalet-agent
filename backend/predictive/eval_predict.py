"""Faz-5 bağımsız eval harness — BERT-TR dava-sonucu modelini ölç (silver + gold).

Mevcut metrics.json eğitim koşumunun raporu (silver test). Bu harness BAĞIMSIZ:
checkpoint'i alır, deterministik test-split (veya insan-doğrulanmış GOLD set) üzerinde
accuracy / macro-F1 / sınıf-başına P-R-F1 / confusion / ECE üretir. Böylece eğitim
çıktısına güvenmeden modeli yeniden ölçer + provenance teyit eder (hangi labeled_v*).

Saf çekirdek (classification_metrics) model/torch GEREKMEZ → birim-test edilir.
Kalibrasyon (softmax+T) ve ECE predictive.calibrate'ten yeniden kullanılır (DRY).

DÜRÜSTLÜK (CLAUDE.md §1): silver-test = zayıf-etiketli (auto_label ~%70 doğru) →
gerçek tavan değil. İnsan-doğrulanmış GOLD set (--gold) varsa ASIL ölçüm odur; yoksa
'silver' olduğu açıkça raporlanır. Gold set kullanıcı tarafından doldurulur (uydurulmaz).

Kullanım:
  uv run python -m predictive.eval_predict                                  # silver test (labeled_v2)
  uv run python -m predictive.eval_predict --data data/predictive/labeled_v2.jsonl
  uv run python -m predictive.eval_predict --gold data/predictive/gold_eval.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows: pyarrow'u torch'tan ÖNCE yükle (transformers→datasets→pyarrow segfault guard).
from core import native_preload  # noqa: F401
from predictive.data_loader import ID2LABEL, LABEL2ID, load_jsonl, stratified_split

_DEFAULT_DATA = "data/predictive/labeled_v2.jsonl"
_DEFAULT_MODEL_DIR = "predictive/checkpoints/best"
_N_CLASSES = len(LABEL2ID)


def classification_metrics(y_true: list[int], y_pred: list[int],
                           n_classes: int = _N_CLASSES) -> dict:
    """Saf — (gerçek, tahmin) id listesinden accuracy + sınıf P/R/F1 + macro + confusion.

    Model/torch/sklearn GEREKMEZ (confusion'dan elde hesaplar) → hermetik test.
    """
    if len(y_true) != len(y_pred):
        raise ValueError(f"y_true ({len(y_true)}) ile y_pred ({len(y_pred)}) farklı")
    conf = [[0] * n_classes for _ in range(n_classes)]
    for t, p in zip(y_true, y_pred, strict=True):
        conf[t][p] += 1
    per_class: dict[str, dict] = {}
    f1s: list[float] = []
    for c in range(n_classes):
        tp = conf[c][c]
        fp = sum(conf[r][c] for r in range(n_classes)) - tp
        fn = sum(conf[c][j] for j in range(n_classes)) - tp
        support = sum(conf[c])
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        f1s.append(f1)
        per_class[ID2LABEL[c]] = {
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "support": support,
        }
    total = len(y_true)
    accuracy = sum(conf[c][c] for c in range(n_classes)) / total if total else 0.0
    return {
        "n": total,
        "accuracy": round(accuracy, 4),
        "f1_macro": round(sum(f1s) / n_classes, 4),
        "per_class": per_class,
        "confusion": conf,
    }


def run_model(records: list[dict], model_dir: str, max_length: int = 512,
              batch_size: int = 32) -> tuple[list[int], list[int], list]:
    """Checkpoint'i kayıtların input_text'i üzerinde koştur → (y_true, y_pred, probs).

    inference._load_model'i yeniden kullanır (aynı tokenizer/model/temperature) — canlı
    inference ile birebir tutarlı. Kalibre softmax (T) uygulanır.
    """
    import numpy as np
    import torch

    from predictive.calibrate import softmax
    from predictive.inference import _load_model

    tok, model, temperature = _load_model(model_dir)
    device = next(model.parameters()).device
    y_true = [LABEL2ID[r["label"]] for r in records]
    y_pred: list[int] = []
    probs_all: list[list[float]] = []
    for i in range(0, len(records), batch_size):
        batch = [r["input_text"] for r in records[i:i + batch_size]]
        enc = tok(batch, truncation=True, max_length=max_length, padding=True,
                  return_tensors="pt").to(device)
        with torch.no_grad():
            logits = model(**enc).logits.cpu().numpy()
        probs = softmax(logits, temperature)
        y_pred.extend(int(p.argmax()) for p in probs)
        probs_all.extend(probs.tolist())
        print(f"    {min(i + batch_size, len(records))}/{len(records)}", end="\r", flush=True)
    return y_true, y_pred, np.asarray(probs_all)


def evaluate(records: list[dict], model_dir: str, max_length: int, label: str) -> dict:
    """Tam rapor: classification_metrics + ECE (kalibre güven)."""
    from predictive.calibrate import expected_calibration_error

    y_true, y_pred, probs = run_model(records, model_dir, max_length)
    report = classification_metrics(y_true, y_pred)
    report["ece"] = expected_calibration_error(probs, y_true)
    report["label_kind"] = label
    return report


def print_scorecard(s: dict) -> None:
    bar = "=" * 66
    kind = s["label_kind"].upper()
    print(f"\n{bar}\n  DAVA-SONUCU TAHMİNİ EVAL — {kind} ({s['n']} örnek)\n{bar}")
    if s["label_kind"] == "silver":
        warn = "  ⚠️ SILVER: zayıf-etiketli (~%70) — gerçek tavan değil; GOLD ile doğrula."
    elif s["label_kind"] == "human":
        warn = "  ✓ GOLD: insan-doğrulanmış set (gerçek doğruluk)."
    else:
        warn = (f"  ⚠️ {kind}: LLM/otomatik referans — İNSAN-doğrulanmış DEĞİL "
                "(silver↔gerçek arası köprü ölçüm).")
    print(warn)
    print(f"  accuracy = {s['accuracy']:.4f}   f1_macro = {s['f1_macro']:.4f}   "
          f"ECE = {s['ece']:.4f} (hedef ≤0.05)")
    print(f"  {'-' * 64}")
    print(f"  {'sınıf':<12}{'precision':>11}{'recall':>9}{'f1':>8}{'support':>9}")
    for lab, m in s["per_class"].items():
        print(f"  {lab:<12}{m['precision']:>11.4f}{m['recall']:>9.4f}{m['f1']:>8.4f}{m['support']:>9}")
    print(f"  {'-' * 64}\n  confusion (satır=gerçek, sütun=tahmin) [{', '.join(ID2LABEL[i] for i in range(_N_CLASSES))}]:")
    for i, row in enumerate(s["confusion"]):
        print(f"    {ID2LABEL[i]:<10} {row}")
    print(bar)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="BERT-TR dava-sonucu eval (silver/gold)")
    parser.add_argument("--data", default=_DEFAULT_DATA, help="Silver JSONL (split'lenir)")
    parser.add_argument("--gold", default=None, help="Referans GOLD JSONL (varsa asıl ölçüm)")
    parser.add_argument("--gold-kind", default="llm-ref", choices=["human", "llm-ref"],
                        help="GOLD kaynağı: human (insan-doğrulanmış) | llm-ref (Qwen-ref köprü)")
    parser.add_argument("--model-dir", default=_DEFAULT_MODEL_DIR)
    parser.add_argument("--split", default="test", choices=["test", "val", "all"])
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if not Path(args.model_dir).is_dir():
        raise SystemExit(f"Model yok: {args.model_dir} — önce predictive.train koş.")

    reports = {}
    if args.gold and Path(args.gold).exists():
        gold = load_jsonl(args.gold)
        print(f"[*] GOLD eval ({args.gold_kind}): {len(gold)} örnek")
        reports["gold"] = evaluate(gold, args.model_dir, args.max_length, args.gold_kind)

    records = load_jsonl(args.data)
    _train, val, test = stratified_split(records, seed=42)
    split = {"test": test, "val": val, "all": records}[args.split]
    print(f"[*] SILVER eval: {args.data} → {args.split} split ({len(split)} örnek)")
    reports["silver"] = evaluate(split, args.model_dir, args.max_length, "silver")

    for r in reports.values():
        print_scorecard(r)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Rapor -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
