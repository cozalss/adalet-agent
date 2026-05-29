"""data_loader saf-fonksiyon testleri (torch/GPU GEREKTİRMEZ).

split stratification + determinism + leak-free + class-weights + jsonl filtre.
"""

from __future__ import annotations

import json

import pytest

from predictive.data_loader import (
    LABEL2ID,
    compute_class_weights,
    label_distribution,
    load_jsonl,
    stratified_split,
)


def _recs(n_kaz=60, n_kay=30, n_kis=10):
    out = []
    for i in range(n_kaz):
        out.append({"doc_id": f"k{i}", "label": "kazandi", "input_text": f"olay {i}"})
    for i in range(n_kay):
        out.append({"doc_id": f"y{i}", "label": "kaybetti", "input_text": f"olay {i}"})
    for i in range(n_kis):
        out.append({"doc_id": f"s{i}", "label": "kismi", "input_text": f"olay {i}"})
    return out


def test_split_proportions_80_10_10():
    train, val, test = stratified_split(_recs(), val_frac=0.1, test_frac=0.1, seed=42)
    total = len(train) + len(val) + len(test)
    assert total == 100
    # ~%80/10/10 (int floor toleransı)
    assert 78 <= len(train) <= 82
    assert 8 <= len(val) <= 12
    assert 8 <= len(test) <= 12


def test_split_is_stratified_all_classes_in_each():
    train, val, test = stratified_split(_recs(), seed=1)
    for part in (train, val, test):
        labels = {r["label"] for r in part}
        # kismi (n=10) bile her split'te temsil edilmeli (10→test1/val1/train8)
        assert "kazandi" in labels and "kaybetti" in labels


def test_split_deterministic_same_seed():
    a = stratified_split(_recs(), seed=7)
    b = stratified_split(_recs(), seed=7)
    assert [r["doc_id"] for r in a[0]] == [r["doc_id"] for r in b[0]]


def test_split_no_leakage_between_partitions():
    train, val, test = stratified_split(_recs(), seed=3)
    ids_train = {r["doc_id"] for r in train}
    ids_val = {r["doc_id"] for r in val}
    ids_test = {r["doc_id"] for r in test}
    assert ids_train.isdisjoint(ids_val)
    assert ids_train.isdisjoint(ids_test)
    assert ids_val.isdisjoint(ids_test)
    assert len(ids_train | ids_val | ids_test) == 100


def test_split_rejects_bad_fractions():
    with pytest.raises(ValueError):
        stratified_split(_recs(), val_frac=0.6, test_frac=0.6)


def test_class_weights_inverse_frequency():
    w = compute_class_weights(_recs(n_kaz=60, n_kay=30, n_kis=10))
    # az olan sınıf (kismi) en yüksek ağırlık
    assert w["kismi"] > w["kaybetti"] > w["kazandi"]


def test_load_jsonl_filters_invalid(tmp_path):
    p = tmp_path / "d.jsonl"
    lines = [
        {"label": "kazandi", "input_text": "x"},          # geçerli
        {"label": "belirsiz", "input_text": "y"},          # 3-class dışı → atla
        {"label": "kaybetti", "input_text": ""},           # boş input → atla
        {"label": "kismi", "input_text": "z"},             # geçerli
    ]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    recs = load_jsonl(p)
    assert len(recs) == 2
    assert {r["label"] for r in recs} == {"kazandi", "kismi"}


def test_label_distribution_counts_only_valid():
    dist = label_distribution(_recs(n_kaz=5, n_kay=3, n_kis=2))
    assert dist == {"kazandi": 5, "kaybetti": 3, "kismi": 2}
    assert set(dist) <= set(LABEL2ID)
