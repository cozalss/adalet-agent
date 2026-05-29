"""Tahmin modeli veri yükleme — JSONL → split → torch.Dataset.

auto_label.py'nin ürettiği leak-free silver-label JSONL'i (input_text + label)
eğitime hazırlar. Saf fonksiyonlar (load/split/weights) torch GEREKTİRMEZ →
GPU'suz unit-test edilir; `OutcomeDataset` torch'u lazy import eder.

Sınıflar (README §Model): kazandi=0, kaybetti=1, kismi=2. "belirsiz" YOK —
auto_label net-sinyalsiz kararları zaten atlar (None), eğitim seti 3-class.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from torch.utils.data import Dataset
else:
    Dataset = object  # torch yoksa modül import edilebilir kalsın

LABEL2ID: dict[str, int] = {"kazandi": 0, "kaybetti": 1, "kismi": 2}
ID2LABEL: dict[int, str] = {v: k for k, v in LABEL2ID.items()}


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """JSONL → kayıt listesi. Yalnız geçerli 3-class label'lı satırlar."""
    records: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("label") in LABEL2ID and rec.get("input_text"):
                records.append(rec)
    return records


def stratified_split(
    records: list[dict[str, Any]],
    val_frac: float = 0.1,
    test_frac: float = 0.1,
    seed: int = 42,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Label-stratified deterministik train/val/test böl (README §Splits 80/10/10).

    Her sınıf ayrı bölünür → dengesiz sınıf (kismi az) tüm split'lerde temsil
    edilir. Aynı seed → aynı bölünme (reproducibility). Split'ler ayrık (leak yok).
    """
    if not 0 < val_frac + test_frac < 1:
        raise ValueError("val_frac + test_frac (0,1) aralığında olmalı")
    by_label: dict[str, list[dict]] = {}
    for rec in records:
        by_label.setdefault(rec["label"], []).append(rec)

    rng = random.Random(seed)
    train: list[dict] = []
    val: list[dict] = []
    test: list[dict] = []
    for label in sorted(by_label):  # sorted → deterministik sıra
        group = by_label[label][:]
        rng.shuffle(group)
        n = len(group)
        n_test = int(n * test_frac)
        n_val = int(n * val_frac)
        test.extend(group[:n_test])
        val.extend(group[n_test:n_test + n_val])
        train.extend(group[n_test + n_val:])
    rng.shuffle(train)
    rng.shuffle(val)
    rng.shuffle(test)
    return train, val, test


def compute_class_weights(records: list[dict[str, Any]]) -> dict[str, float]:
    """Ters-frekans sınıf ağırlıkları (dengesiz kismi için loss weighting).

    weight[c] = N / (n_classes * count[c]). Eşit dağılımda hepsi 1.0.
    """
    counts = Counter(r["label"] for r in records if r.get("label") in LABEL2ID)
    total = sum(counts.values())
    n_classes = len(counts)
    if not total or not n_classes:
        return {}
    return {
        label: round(total / (n_classes * cnt), 4)
        for label, cnt in counts.items()
    }


def label_distribution(records: list[dict[str, Any]]) -> dict[str, int]:
    """Sınıf dağılımı (rapor/dengesizlik kontrolü)."""
    return dict(Counter(r["label"] for r in records if r.get("label") in LABEL2ID))


class OutcomeDataset(Dataset):
    """torch Dataset — input_text'i tokenize eder, label id döner.

    torch lazy import (saf fonksiyonların GPU'suz test edilebilmesi için).
    """

    def __init__(self, records: list[dict[str, Any]], tokenizer: Any, max_length: int = 512) -> None:
        self._records = records
        self._tokenizer = tokenizer
        self._max_length = max_length

    def __len__(self) -> int:
        return len(self._records)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        import torch
        rec = self._records[idx]
        enc = self._tokenizer(
            rec["input_text"],
            truncation=True,
            max_length=self._max_length,
            padding="max_length",
            return_tensors="pt",
        )
        return {
            "input_ids": enc["input_ids"].squeeze(0),
            "attention_mask": enc["attention_mask"].squeeze(0),
            "labels": torch.tensor(LABEL2ID[rec["label"]], dtype=torch.long),
        }


__all__ = (
    "ID2LABEL",
    "LABEL2ID",
    "OutcomeDataset",
    "compute_class_weights",
    "label_distribution",
    "load_jsonl",
    "stratified_split",
)
