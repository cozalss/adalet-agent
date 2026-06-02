"""predictive/eval_predict.py — saf metrik çekirdeği testleri (model/torch GEREKMEZ)."""

from __future__ import annotations

import pytest

from predictive.data_loader import LABEL2ID
from predictive.eval_predict import classification_metrics


def test_perfect_classification():
    y = [0, 1, 2, 0, 1, 2]
    s = classification_metrics(y, list(y))
    assert s["accuracy"] == 1.0
    assert s["f1_macro"] == 1.0
    for m in s["per_class"].values():
        assert m["precision"] == 1.0 and m["recall"] == 1.0


def test_known_confusion_metrics():
    # kazandi(0): 2 doğru; kaybetti(1): 1 doğru 1 yanlış(→0); kismi(2): 2 doğru
    y_true = [0, 0, 1, 1, 2, 2]
    y_pred = [0, 0, 1, 0, 2, 2]
    s = classification_metrics(y_true, y_pred)
    assert s["n"] == 6
    assert s["accuracy"] == round(5 / 6, 4)
    # kazandi: tp=2, fp=1 (kaybetti'den gelen), fn=0 → precision 2/3, recall 1.0
    kz = s["per_class"]["kazandi"]
    assert kz["precision"] == round(2 / 3, 4)
    assert kz["recall"] == 1.0
    # kaybetti: tp=1, fp=0, fn=1 → precision 1.0, recall 0.5
    kb = s["per_class"]["kaybetti"]
    assert kb["precision"] == 1.0 and kb["recall"] == 0.5
    assert s["per_class"]["kaybetti"]["support"] == 2


def test_confusion_matrix_shape_and_counts():
    s = classification_metrics([0, 1, 2], [0, 1, 2])
    assert len(s["confusion"]) == len(LABEL2ID)
    assert s["confusion"][0][0] == 1 and s["confusion"][1][1] == 1


def test_length_mismatch_raises():
    with pytest.raises(ValueError, match="farklı"):
        classification_metrics([0, 1], [0])


def test_empty_is_zero():
    s = classification_metrics([], [])
    assert s["accuracy"] == 0.0 and s["n"] == 0
