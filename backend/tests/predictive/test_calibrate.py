"""calibrate testleri — temperature scaling + ECE (saf numpy, GPU'suz)."""

from __future__ import annotations

import numpy as np
import pytest

from predictive.calibrate import (
    expected_calibration_error,
    fit_temperature,
    softmax,
)


def test_softmax_sums_to_one():
    p = softmax(np.array([[1.0, 2.0, 3.0]]))
    assert p.shape == (1, 3)
    assert abs(p.sum() - 1.0) < 1e-9


def test_softmax_temperature_smooths():
    logits = np.array([[2.0, 1.0, 0.0]])
    sharp = softmax(logits, temperature=0.5).max()
    soft = softmax(logits, temperature=5.0).max()
    assert sharp > soft  # düşük T daha keskin (yüksek güven)


def test_softmax_rejects_nonpositive_temperature():
    with pytest.raises(ValueError):
        softmax(np.array([[1.0, 2.0]]), temperature=0.0)


def test_temperature_does_not_change_argmax():
    """KRİTİK: kalibrasyon accuracy'yi DEĞİŞTİRMEZ (argmax T'den bağımsız)."""
    rng = np.random.default_rng(0)
    logits = rng.normal(size=(50, 3))
    base = logits.argmax(axis=-1)
    for t in (0.3, 1.0, 4.0):
        assert np.array_equal(softmax(logits, t).argmax(axis=-1), base)


def test_fit_temperature_softens_overconfident_logits():
    """Aşırı-güvenli (büyük) logit'ler için fit T > 1 (yumuşatma) bulmalı."""
    rng = np.random.default_rng(42)
    n = 300
    labels = rng.integers(0, 3, size=n)
    # Aşırı-güvenli: doğru sınıfa büyük logit ama %25 gürültülü (yanlış)
    logits = rng.normal(scale=0.5, size=(n, 3))
    for i in range(n):
        if rng.random() > 0.25:
            logits[i, labels[i]] += 6.0      # çok büyük → aşırı güven
        else:
            wrong = (labels[i] + 1) % 3
            logits[i, wrong] += 6.0          # güvenle yanlış
    t = fit_temperature(logits, labels)
    assert t > 1.0  # aşırı-güveni yumuşatmalı


def test_fit_temperature_validates_shape():
    with pytest.raises(ValueError):
        fit_temperature(np.array([1.0, 2.0, 3.0]), np.array([0]))


def test_ece_zero_when_perfectly_calibrated():
    """Güven == doğruluk → ECE ≈ 0."""
    # 2 örnek: biri güven 1.0 doğru, biri güven 1.0 doğru → ECE 0
    probs = np.array([[0.99, 0.005, 0.005], [0.005, 0.99, 0.005]])
    labels = np.array([0, 1])
    assert expected_calibration_error(probs, labels) < 0.02


def test_ece_high_when_overconfident_and_wrong():
    """Yüksek güvenle yanlış → yüksek ECE."""
    probs = np.array([[0.95, 0.03, 0.02]] * 10)  # hep %95 güven sınıf-0
    labels = np.array([1] * 10)                   # ama hep yanlış (sınıf-1)
    ece = expected_calibration_error(probs, labels)
    assert ece > 0.5  # güven %95, doğruluk %0 → büyük fark


def test_ece_empty_is_zero():
    assert expected_calibration_error(np.empty((0, 3)), np.array([], dtype=int)) == 0.0
