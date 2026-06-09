"""Eğitilmiş BERT modelini temperature-scaling ile kalibre et (GPU/CPU).

train.py'nin ürettiği checkpoint'i val-set'te koşar, logit toplar, calibrate.py
ile optimal T'yi fit eder, ECE-öncesi/sonrası raporlar, `temperature.json`'u
model dizinine yazar → inference.py bunu otomatik okur (güven kalibrasyonu).

Kullanım:
    uv run python -m scripts.predictive.calibrate_model \
        --model predictive/checkpoints/best --data data/predictive/labeled_v1.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Windows: pyarrow'u torch'tan ÖNCE yükle (segfault guard).
from core import native_preload  # noqa: F401
from predictive.data_loader import LABEL2ID, load_jsonl, stratified_split

logger = logging.getLogger("scripts.predictive.calibrate_model")


def _run(args: argparse.Namespace) -> int:
    import numpy as np
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    from predictive.calibrate import expected_calibration_error, fit_temperature, softmax

    # GUARD: kalibrasyon, modelin EĞİTİLDİĞİ veriyle aynı --data ile koşmalı;
    # yoksa val-split farklı örnekler üretir → yanlış kalibrasyon (sessiz hata).
    metrics_path = Path(args.model) / "metrics.json"
    if metrics_path.exists():
        trained_on = json.loads(metrics_path.read_text(encoding="utf-8")).get("data")
        if trained_on and trained_on != Path(args.data).name:
            logger.warning(
                "veri uyuşmazlığı: model '%s' ile eğitilmiş ama --data '%s' — "
                "kalibrasyon YANLIŞ olur. Eğitim verisini ver.",
                trained_on, Path(args.data).name,
            )

    records = load_jsonl(args.data)
    # train.py ile AYNI split (seed=42) → val T-fit için, test HELD-OUT ECE için ayrık.
    _train, val_recs, test_recs = stratified_split(
        records, val_frac=args.val_frac, test_frac=args.test_frac, seed=args.seed,
    )
    logger.info("kalibrasyon: T-fit val=%d, held-out test=%d", len(val_recs), len(test_recs))

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(args.model)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).eval()

    def _logits_labels(recs: list[dict]):  # → (logits NDArray, labels NDArray)
        ll: list[list[float]] = []
        lb: list[int] = []
        with torch.no_grad():
            for i in range(0, len(recs), args.batch_size):
                batch = recs[i:i + args.batch_size]
                enc = tokenizer(
                    [r["input_text"] for r in batch],
                    truncation=True, max_length=args.max_length,
                    padding=True, return_tensors="pt",
                ).to(device)
                logits = model(**enc).logits.cpu().numpy()
                ll.extend(logits.tolist())
                lb.extend(LABEL2ID[r["label"]] for r in batch)
        return np.asarray(ll, dtype=np.float64), np.asarray(lb)

    logits_arr, labels_arr = _logits_labels(val_recs)

    # T'yi VAL'de fit et. UYARI: aynı sette raporlanan ECE in-sample → İYİMSER (double-dip,
    # kullanıcı-inceleme #2) → ayrıca held-out test'te ölçülür (aşağıda, dürüst sayı).
    ece_before = expected_calibration_error(softmax(logits_arr, 1.0), labels_arr)
    fitted_t = fit_temperature(logits_arr, labels_arr)
    ece_fitted = expected_calibration_error(softmax(logits_arr, fitted_t), labels_arr)

    # GUARD: T'yi yalnız ECE'yi İYİLEŞTİRİYORSA uygula. NLL-optimal T küçük
    # val-set'te (Guo 2017) ECE'yi bazen hafif kötüleştirir; model zaten
    # kalibreyse (ECE düşük) T=1 bırak — kötü kalibrasyon shipleme (dürüstlük).
    if ece_fitted < ece_before:
        final_t, final_ece = fitted_t, ece_fitted
        applied = True
    else:
        final_t, final_ece = 1.0, ece_before
        applied = False

    # DÜRÜST kalibrasyon ölçümü (#2): T'nin fit EDİLMEDİĞİ held-out test split'inde ECE —
    # generalization tahmini. `ece` (in-sample/val) double-dip nedeniyle iyimserdir.
    ece_heldout: float | None = None
    if test_recs:
        logits_te, labels_te = _logits_labels(test_recs)
        ece_heldout = expected_calibration_error(softmax(logits_te, final_t), labels_te)

    out = {
        "temperature": final_t,
        "ece": final_ece,             # in-sample (val, T-fit seti) — İYİMSER, double-dip
        "ece_heldout": ece_heldout,   # held-out (test) — DÜRÜST generalization ECE (#2)
        "ece_before": ece_before,
        "ece_fitted": ece_fitted,
        "fitted_temperature": fitted_t,
        "temperature_applied": applied,
        "n_val": len(val_recs),
        "n_test": len(test_recs),
    }
    temp_path = Path(args.model) / "temperature.json"
    temp_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("=" * 56)
    logger.info("ECE öncesi (T=1): %.4f | NLL-fit T=%.3f → ECE %.4f",
                ece_before, fitted_t, ece_fitted)
    logger.info("KARAR: T=%.4f uygulandı=%s → in-sample ECE=%.4f (val/T-fit seti — İYİMSER)",
                final_t, applied, final_ece)
    if ece_heldout is not None:
        logger.info("HELD-OUT ECE (test, DÜRÜST generalization): %.4f (hedef ≤0.05)", ece_heldout)
    else:
        logger.info("UYARI: test split boş — yalnız in-sample ECE var (iyimser olabilir).")
    if not applied:
        logger.info("Model zaten kalibre — temperature scaling iyileştirmedi, T=1 korundu.")
    logger.info("Yazıldı: %s (inference.py otomatik okur)", temp_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.predictive.calibrate_model")
    parser.add_argument("--model", default="predictive/checkpoints/best")
    parser.add_argument("--data", default="data/predictive/labeled_v1.jsonl")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-length", type=int, default=384)
    parser.add_argument("--val-frac", type=float, default=0.1)
    parser.add_argument("--test-frac", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
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
