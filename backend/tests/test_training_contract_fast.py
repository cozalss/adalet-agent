"""Fast training contract tests included in the main backend suite."""

from __future__ import annotations

import json

from training.lora_embedding import TrainConfig, load_triplets, split_train_val


def test_lora_train_config_contract_is_sane() -> None:
    cfg = TrainConfig()
    assert cfg.epochs >= 1
    assert cfg.batch_size >= 1
    assert 0.0 < cfg.learning_rate < 1.0
    assert cfg.lora_r > 0
    assert 0.0 <= cfg.lora_dropout < 1.0
    assert 0.0 < cfg.val_split < 1.0
    assert {"query", "key", "value", "dense"}.issubset(set(cfg.target_modules))


def test_load_triplets_contract_skips_bad_rows(tmp_path) -> None:
    path = tmp_path / "train.jsonl"
    rows = [
        {"anchor": "a1", "positive": "p1", "negative": "n1"},
        {"anchor": "missing fields"},
        "not json",
        {"anchor": "a2", "positive": "p2", "negative": "n2"},
    ]
    path.write_text(
        "\n".join(
            row if isinstance(row, str) else json.dumps(row, ensure_ascii=False)
            for row in rows
        ),
        encoding="utf-8",
    )

    out = load_triplets(path)

    assert out == [
        {"anchor": "a1", "positive": "p1", "negative": "n1"},
        {"anchor": "a2", "positive": "p2", "negative": "n2"},
    ]


def test_split_train_val_contract_is_deterministic() -> None:
    triplets = [{"anchor": f"a{i}", "positive": "p", "negative": "n"} for i in range(20)]

    train1, val1 = split_train_val(triplets, val_split=0.2, seed=42)
    train2, val2 = split_train_val(triplets, val_split=0.2, seed=42)

    assert train1 == train2
    assert val1 == val2
    assert len(val1) == 4
    assert len(train1) == 16
