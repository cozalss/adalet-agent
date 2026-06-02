"""eval/nli_tr_eval.py — saf metrik fonksiyonu testleri (NLI modeli GEREKMEZ).

score_predictions / threshold_sweep saf: tahmin listeleri verilir, model yüklenmez.
Gerçek mDeBERTa ölçümü __main__ (preload) ile çalışır; bu testler matematik + gold
bütünlüğünü doğrular (hermetic, hızlı).
"""

from __future__ import annotations

import pytest

from eval.nli_tr_eval import (
    GOLD_PATH,
    LABELS,
    LabelMetric,
    load_gold,
    score_predictions,
    threshold_sweep,
)


def test_label_metric_math():
    m = LabelMetric("contradiction", tp=6, fp=0, fn=2)
    assert m.precision == 1.0
    assert m.recall == 0.75
    assert m.f1 == round(2 * 1.0 * 0.75 / 1.75, 3)


def test_label_metric_no_predictions_is_precise():
    m = LabelMetric("x", tp=0, fp=0, fn=0)
    assert m.precision == 1.0 and m.recall == 1.0


def test_score_predictions_perfect():
    gold = ["entailment", "neutral", "contradiction"]
    s = score_predictions(gold, list(gold))
    assert s["accuracy"] == 1.0
    assert s["contra_false_positives"] == 0
    assert s["contra_false_positive_rate"] == 0.0
    assert s["contradiction_recall"] == 1.0


def test_score_predictions_counts_contradiction_false_positive():
    # 2 entailment + 1 neutral (3 non-contra), biri yanlışlıkla contradiction sanıldı.
    gold = ["entailment", "entailment", "neutral", "contradiction"]
    pred = ["contradiction", "entailment", "neutral", "contradiction"]
    s = score_predictions(gold, pred)
    assert s["contra_false_positives"] == 1
    assert s["n_non_contradiction"] == 3
    assert s["contra_false_positive_rate"] == round(1 / 3, 3)
    assert s["contradiction_recall"] == 1.0  # gerçek çelişki yakalandı


def test_score_predictions_missed_contradiction_lowers_recall():
    gold = ["contradiction", "contradiction", "entailment"]
    pred = ["contradiction", "neutral", "entailment"]  # biri kaçtı
    s = score_predictions(gold, pred)
    assert s["contradiction_recall"] == 0.5
    assert s["contra_false_positives"] == 0


def test_score_predictions_length_mismatch_raises():
    with pytest.raises(ValueError, match="uzunluğu farklı"):
        score_predictions(["entailment"], ["entailment", "neutral"])


def test_threshold_sweep_monotonic_false_veto():
    # Eşik yükseldikçe yanlış-veto AZALMALI (monoton), yakalama da azalır.
    gold = ["contradiction", "contradiction", "entailment", "neutral"]
    con = [0.95, 0.55, 0.45, 0.30]  # contra skorları
    sweep = threshold_sweep(gold, con, thresholds=(0.40, 0.50, 0.70, 0.90))
    fv = [row["false_veto"] for row in sweep]
    assert fv == sorted(fv, reverse=True)  # monoton azalan
    # th=0.40: entailment(0.45) yanlış-veto edilir; th=0.50'de edilmez
    assert sweep[0]["false_veto"] == 1
    assert sweep[2]["false_veto"] == 0  # th=0.70


def test_threshold_sweep_recall_at_production():
    gold = ["contradiction", "contradiction"]
    con = [0.95, 0.65]
    sweep = threshold_sweep(gold, con, thresholds=(0.70,))
    assert sweep[0]["contradiction_recall"] == 0.5  # 0.65 < 0.70 kaçar


# --- Gold-set bütünlüğü (veri sağlığı) ---

def test_gold_set_loads_and_labels_valid():
    rows = load_gold(GOLD_PATH)
    assert len(rows) >= 24
    for r in rows:
        assert r["label"] in LABELS
        assert r["premise"].strip() and r["hypothesis"].strip()
        assert r["id"]


def test_gold_set_has_all_three_classes():
    rows = load_gold(GOLD_PATH)
    labels = {r["label"] for r in rows}
    assert labels == set(LABELS)


def test_gold_set_ids_unique():
    rows = load_gold(GOLD_PATH)
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
