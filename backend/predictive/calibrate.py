"""Güven kalibrasyonu — temperature scaling + ECE (README hedef: ECE ≤ 0.05).

Vatandaşa "%80 kazanırsın" demek, GERÇEKTEN %80 kazanılan davalar grubunda olmak
demektir (CLAUDE.md §1 dürüstlük). Ham softmax aşırı-güvenlidir; tek-parametreli
**temperature scaling** (Guo et al. 2017) logit'leri T ile ölçekleyip kalibre eder
— Platt'tan basit, sinir ağı çok-sınıf için standart, accuracy'yi DEĞİŞTİRMEZ
(argmax sabit; yalnız güven düzelir).

Saf numpy — torch/GPU GEREKTİRMEZ, tam unit-test'li. train.py val-logit'leriyle
fit edilir, inference.py BERT versiyonunda apply edilir.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def softmax(logits: NDArray[np.float64], temperature: float = 1.0) -> NDArray[np.float64]:
    """Sıcaklık-ölçekli softmax. T>1 → yumuşatır (daha az güven); T<1 → keskinleştirir."""
    if temperature <= 0:
        raise ValueError("temperature > 0 olmalı")
    z = np.asarray(logits, dtype=np.float64) / temperature
    z = z - z.max(axis=-1, keepdims=True)   # numerik stabilite
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def _nll(logits: NDArray[np.float64], labels: NDArray[np.int_], temperature: float) -> float:
    """Negatif log-likelihood (temperature fit hedefi)."""
    probs = softmax(logits, temperature)
    n = len(labels)
    true_p = probs[np.arange(n), labels]
    return float(-np.log(np.clip(true_p, 1e-12, 1.0)).mean())


def fit_temperature(
    logits: NDArray[np.float64],
    labels: NDArray[np.int_],
    lo: float = 0.05,
    hi: float = 10.0,
    iters: int = 50,
) -> float:
    """Val-set NLL'ini minimize eden T'yi bul (golden-section search, türevsiz).

    Tek parametre → 1-D arama yeter (scipy'siz). accuracy'yi etkilemez (argmax
    T'den bağımsız), yalnız güven kalibrasyonunu düzeltir.
    """
    logits = np.asarray(logits, dtype=np.float64)
    labels = np.asarray(labels)
    if logits.ndim != 2 or len(logits) != len(labels):
        raise ValueError("logits (N,C) ve labels (N,) uyumlu olmalı")

    inv_phi = (np.sqrt(5.0) - 1) / 2          # 0.618...
    a, b = lo, hi
    c = b - inv_phi * (b - a)
    d = a + inv_phi * (b - a)
    fc, fd = _nll(logits, labels, c), _nll(logits, labels, d)
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - inv_phi * (b - a)
            fc = _nll(logits, labels, c)
        else:
            a, c, fc = c, d, fd
            d = a + inv_phi * (b - a)
            fd = _nll(logits, labels, d)
    return round((a + b) / 2, 4)


def expected_calibration_error(
    probs: NDArray[np.float64],
    labels: NDArray[np.int_],
    n_bins: int = 10,
) -> float:
    """ECE — güven ile gerçek doğruluk arasındaki ağırlıklı fark (README ≤0.05).

    Tahminleri max-güvene göre n_bins kovaya böl; her kovada |ortalama güven −
    doğruluk| × (kova payı) topla.
    """
    probs = np.asarray(probs, dtype=np.float64)
    labels = np.asarray(labels)
    conf = probs.max(axis=-1)
    pred = probs.argmax(axis=-1)
    correct = (pred == labels).astype(np.float64)
    n = len(labels)
    if n == 0:
        return 0.0
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        lo_e, hi_e = edges[i], edges[i + 1]
        # son kova üst-kapalı (conf==1.0 dahil)
        mask = (conf > lo_e) & (conf <= hi_e) if i > 0 else (conf >= lo_e) & (conf <= hi_e)
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        ece += (cnt / n) * abs(conf[mask].mean() - correct[mask].mean())
    return round(float(ece), 4)


__all__ = (
    "expected_calibration_error",
    "fit_temperature",
    "softmax",
)
