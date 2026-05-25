"""LoRA training — dataset utilities (heavy bağımlılıklar olmadan)."""

from __future__ import annotations

import json

import pytest

from training.lora_embedding import (
    TrainConfig,
    load_triplets,
    split_train_val,
)


def test_train_config_defaults_sane():
    cfg = TrainConfig()
    assert cfg.epochs >= 1
    assert cfg.batch_size >= 1
    assert 0.0 < cfg.learning_rate < 1.0
    assert cfg.lora_r > 0
    assert 0.0 <= cfg.lora_dropout < 1.0
    assert 0.0 < cfg.val_split < 1.0
    assert "query" in cfg.target_modules


def test_load_triplets_reads_jsonl(tmp_path):
    p = tmp_path / "train.jsonl"
    lines = [
        {"anchor": "a1", "positive": "p1", "negative": "n1"},
        {"anchor": "a2", "positive": "p2", "negative": "n2"},
        {"anchor": "a3", "positive": "p3", "negative": "n3"},
    ]
    p.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines),
        encoding="utf-8",
    )
    out = load_triplets(p)
    assert len(out) == 3
    assert all(set(t.keys()) >= {"anchor", "positive", "negative"} for t in out)


def test_load_triplets_skips_bad_lines(tmp_path):
    """Bozuk JSON / eksik alan → atlanır, geri kalan okunur."""
    p = tmp_path / "train.jsonl"
    p.write_text(
        '{"anchor": "a", "positive": "p", "negative": "n"}\n'
        'invalid json line\n'
        '{"anchor": "a2"}\n'  # eksik alan
        '\n'
        '{"anchor": "a3", "positive": "p3", "negative": "n3"}\n',
        encoding="utf-8",
    )
    out = load_triplets(p)
    assert len(out) == 2


def test_load_triplets_missing_file_returns_empty(tmp_path):
    out = load_triplets(tmp_path / "yok.jsonl")
    assert out == []


def test_split_train_val_deterministic():
    triplets = [{"anchor": f"a{i}", "positive": "p", "negative": "n"} for i in range(10)]
    train1, val1 = split_train_val(triplets, val_split=0.2, seed=42)
    train2, val2 = split_train_val(triplets, val_split=0.2, seed=42)
    assert train1 == train2
    assert val1 == val2
    assert len(val1) >= 1
    assert len(train1) + len(val1) == 10


def test_split_train_val_different_seed_yields_different_split():
    triplets = [{"anchor": f"a{i}", "positive": "p", "negative": "n"} for i in range(20)]
    _, val_a = split_train_val(triplets, val_split=0.2, seed=1)
    _, val_b = split_train_val(triplets, val_split=0.2, seed=2)
    # Farklı seed → en az bir farklı eleman bekleriz
    assert val_a != val_b


def test_split_train_val_empty():
    train, val = split_train_val([], val_split=0.1, seed=42)
    assert train == []
    assert val == []


def test_train_lora_raises_without_dataset(tmp_path):
    """Veri yoksa train_lora açıklayıcı RuntimeError fırlatır."""
    from training.lora_embedding import train_lora
    cfg = TrainConfig(dataset_path=tmp_path / "nope.jsonl")
    with pytest.raises(RuntimeError, match="Dataset bos"):
        train_lora(cfg)


def test_lora_dataset_builder_module_imports():
    """dataset_builder modülü import edilebilmeli (Qdrant runtime degil, yalnız tanım)."""
    from training import dataset_builder
    assert hasattr(dataset_builder, "build_triplets")
    assert hasattr(dataset_builder, "TripletExample")
