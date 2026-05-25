"""PEFT LoRA fine-tune — BGE-M3 backbone (XLM-R encoder) Türkçe hukuk için.

Yaklaşım: Triplet loss (anchor, positive, negative) — anchor=karar snippet,
positive=atıfta bulunulan madde, negative=aynı domain başka madde.

Neden LoRA? BGE-M3 backbone'unu (572M XLM-R + dense head) tam fine-tune
12GB VRAM'a sığmaz. LoRA r=16 adapter ~%0.5 parametre (3M) — tek 4070 GPU'da
4-8 saat eğitim. CPU fallback de mümkün (yavaş ama çalışır).

Çıktı: `data/lora/bge-m3-adalet/adapter_model.safetensors` + config.

Production'da `retrieval/embedding.py` LoRA adapter'ı opsiyonel yükler:
    Embedder(lora_path="data/lora/bge-m3-adalet/")

Default-safe: bu modül peft/datasets yoksa ImportError raise eder — sadece
training extra (`uv sync --extra lora`) ile kurulur. Production runtime'a
sızmaz.

Çalıştır:
    uv run python -m training.lora_embedding \\
        --dataset data/lora/train.jsonl \\
        --output data/lora/bge-m3-adalet \\
        --epochs 3 --batch-size 8 --lr 1e-4
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

# UTF-8 zorla (Windows cp1254)
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

log = structlog.get_logger()

DEFAULT_BASE = os.getenv("LORA_BASE_MODEL", "BAAI/bge-m3")
DEFAULT_OUTPUT = Path(os.getenv("LORA_OUTPUT_DIR", "data/lora/bge-m3-adalet"))
DEFAULT_DATASET = Path(os.getenv("LORA_DATASET_PATH", "data/lora/train.jsonl"))
DEFAULT_EPOCHS = int(os.getenv("LORA_EPOCHS", "3"))
DEFAULT_BATCH = int(os.getenv("LORA_BATCH_SIZE", "8"))
DEFAULT_LR = float(os.getenv("LORA_LEARNING_RATE", "1e-4"))
DEFAULT_R = int(os.getenv("LORA_R", "16"))
DEFAULT_ALPHA = int(os.getenv("LORA_ALPHA", "32"))
DEFAULT_DROPOUT = float(os.getenv("LORA_DROPOUT", "0.05"))
DEFAULT_MAX_LEN = int(os.getenv("LORA_MAX_LENGTH", "512"))
DEFAULT_TRIPLET_MARGIN = float(os.getenv("LORA_TRIPLET_MARGIN", "0.2"))
DEFAULT_VAL_SPLIT = float(os.getenv("LORA_VAL_SPLIT", "0.1"))


@dataclass(slots=True)
class TrainConfig:
    """LoRA eğitim konfigurasyonu — CLI args ile dolu."""

    dataset_path: Path = DEFAULT_DATASET
    output_dir: Path = DEFAULT_OUTPUT
    base_model: str = DEFAULT_BASE
    epochs: int = DEFAULT_EPOCHS
    batch_size: int = DEFAULT_BATCH
    learning_rate: float = DEFAULT_LR
    lora_r: int = DEFAULT_R
    lora_alpha: int = DEFAULT_ALPHA
    lora_dropout: float = DEFAULT_DROPOUT
    max_length: int = DEFAULT_MAX_LEN
    triplet_margin: float = DEFAULT_TRIPLET_MARGIN
    val_split: float = DEFAULT_VAL_SPLIT
    seed: int = 42
    # Target modules — XLM-R RoBERTa attention proje katmanları
    target_modules: tuple[str, ...] = field(
        default_factory=lambda: ("query", "key", "value", "dense"),
    )


@dataclass(slots=True)
class TrainResult:
    """Eğitim sonu özet — test/eval icin sample-friendly."""

    n_train: int
    n_val: int
    epochs: int
    final_train_loss: float
    final_val_loss: float
    adapter_path: Path


# --------------------------------------------------------------------------
#  Dataset
# --------------------------------------------------------------------------

def load_triplets(path: Path) -> list[dict[str, Any]]:
    """JSONL dosyasını oku. {"anchor","positive","negative"} alanlarını döner."""
    triplets: list[dict[str, Any]] = []
    if not path.exists():
        log.warning("dataset_missing", path=str(path))
        return triplets
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if all(k in item for k in ("anchor", "positive", "negative")):
                triplets.append(item)
    log.info("dataset_loaded", n=len(triplets), path=str(path))
    return triplets


def split_train_val(
    triplets: list[dict[str, Any]], val_split: float, seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministik train/val ayır."""
    import random as _r
    rng = _r.Random(seed)
    indices = list(range(len(triplets)))
    rng.shuffle(indices)
    n_val = max(1, int(len(triplets) * val_split)) if triplets else 0
    val_idx = set(indices[:n_val])
    train = [t for i, t in enumerate(triplets) if i not in val_idx]
    val = [t for i, t in enumerate(triplets) if i in val_idx]
    return train, val


# --------------------------------------------------------------------------
#  Model + LoRA setup
# --------------------------------------------------------------------------

def _check_peft_available() -> None:
    """peft/datasets kurulu mu? — yoksa açıklayıcı ImportError."""
    try:
        import peft  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "PEFT kurulu degil. LoRA training icin: `uv sync --extra lora`",
        ) from exc


def _build_lora_model(cfg: TrainConfig):
    """BGE-M3 backbone (XLM-R encoder) üzerine LoRA adapter ekle."""
    _check_peft_available()
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModel, AutoTokenizer

    log.info("lora_loading_base", model=cfg.base_model)
    tokenizer = AutoTokenizer.from_pretrained(cfg.base_model)
    model = AutoModel.from_pretrained(cfg.base_model)

    lora_cfg = LoraConfig(
        r=cfg.lora_r,
        lora_alpha=cfg.lora_alpha,
        lora_dropout=cfg.lora_dropout,
        bias="none",
        task_type=TaskType.FEATURE_EXTRACTION,
        target_modules=list(cfg.target_modules),
    )
    model = get_peft_model(model, lora_cfg)
    n_train = sum(p.numel() for p in model.parameters() if p.requires_grad)
    n_total = sum(p.numel() for p in model.parameters())
    log.info(
        "lora_attached",
        trainable=n_train, total=n_total, pct=round(100.0 * n_train / n_total, 3),
    )
    return tokenizer, model


# --------------------------------------------------------------------------
#  Training loop
# --------------------------------------------------------------------------

def train_lora(cfg: TrainConfig) -> TrainResult:
    """LoRA fine-tune ana entrypoint. Triplet loss + AdamW."""
    import torch
    from torch.nn import functional as F  # noqa: N812

    triplets = load_triplets(cfg.dataset_path)
    if not triplets:
        raise RuntimeError(
            f"Dataset bos: {cfg.dataset_path}. "
            "`uv run python -m training.dataset_builder` ile uretin.",
        )

    train, val = split_train_val(triplets, cfg.val_split, cfg.seed)
    log.info("split", train=len(train), val=len(val))

    tokenizer, model = _build_lora_model(cfg)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    log.info("device", device=device)

    optim = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad),
        lr=cfg.learning_rate, weight_decay=0.01,
    )

    def _encode_batch(texts: list[str]) -> Any:
        enc = tokenizer(
            texts, padding=True, truncation=True,
            max_length=cfg.max_length, return_tensors="pt",
        ).to(device)
        out = model(**enc)
        # CLS pooling — BGE-M3 dense head ile uyumlu
        cls = out.last_hidden_state[:, 0, :]
        return F.normalize(cls, p=2, dim=-1)

    def _triplet_loss_epoch(samples: list[dict[str, Any]], training: bool) -> float:
        if not samples:
            return 0.0
        model.train(training)
        total = 0.0
        n_batches = 0
        for i in range(0, len(samples), cfg.batch_size):
            batch = samples[i : i + cfg.batch_size]
            anc = _encode_batch([s["anchor"] for s in batch])
            pos = _encode_batch([s["positive"] for s in batch])
            neg = _encode_batch([s["negative"] for s in batch])
            loss = F.triplet_margin_with_distance_loss(
                anchor=anc, positive=pos, negative=neg,
                distance_function=lambda a, b: 1.0 - (a * b).sum(dim=-1),
                margin=cfg.triplet_margin,
            )
            if training:
                optim.zero_grad()
                loss.backward()
                optim.step()
            total += float(loss.item())
            n_batches += 1
        return total / max(n_batches, 1)

    final_train_loss = 0.0
    final_val_loss = 0.0
    for epoch in range(cfg.epochs):
        tl = _triplet_loss_epoch(train, training=True)
        with torch.no_grad():
            vl = _triplet_loss_epoch(val, training=False)
        log.info("epoch_done", epoch=epoch + 1, train_loss=round(tl, 4), val_loss=round(vl, 4))
        final_train_loss, final_val_loss = tl, vl

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(cfg.output_dir)
    tokenizer.save_pretrained(cfg.output_dir)
    log.info("lora_saved", path=str(cfg.output_dir))

    return TrainResult(
        n_train=len(train),
        n_val=len(val),
        epochs=cfg.epochs,
        final_train_loss=final_train_loss,
        final_val_loss=final_val_loss,
        adapter_path=cfg.output_dir,
    )


# --------------------------------------------------------------------------
#  CLI
# --------------------------------------------------------------------------

def _parse_args() -> TrainConfig:
    parser = argparse.ArgumentParser(description="BGE-M3 PEFT LoRA Türkçe hukuk fine-tune")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--base-model", default=DEFAULT_BASE)
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--lr", type=float, default=DEFAULT_LR)
    parser.add_argument("--lora-r", type=int, default=DEFAULT_R)
    parser.add_argument("--lora-alpha", type=int, default=DEFAULT_ALPHA)
    parser.add_argument("--lora-dropout", type=float, default=DEFAULT_DROPOUT)
    parser.add_argument("--max-length", type=int, default=DEFAULT_MAX_LEN)
    parser.add_argument("--margin", type=float, default=DEFAULT_TRIPLET_MARGIN)
    parser.add_argument("--val-split", type=float, default=DEFAULT_VAL_SPLIT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    return TrainConfig(
        dataset_path=args.dataset,
        output_dir=args.output,
        base_model=args.base_model,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        max_length=args.max_length,
        triplet_margin=args.margin,
        val_split=args.val_split,
        seed=args.seed,
    )


def main() -> int:
    cfg = _parse_args()
    res = train_lora(cfg)
    print(
        f"[OK] LoRA done | train={res.n_train} val={res.n_val} "
        f"final_train_loss={res.final_train_loss:.4f} "
        f"final_val_loss={res.final_val_loss:.4f}",
    )
    print(f"[OK] Adapter: {res.adapter_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ("TrainConfig", "TrainResult", "load_triplets", "split_train_val", "train_lora")
