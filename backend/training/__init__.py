"""Sprint-7/8 — Domain adaptation (BGE-M3 LoRA) modulleri.

LoRA fine-tune iki adımda yapılır:
  1. `dataset_builder.py` — Qdrant'tan pozitif (madde, karar) çiftleri çıkarır,
     hard-negative miner ile contrastive triplet üretir, JSONL yazar.
  2. `lora_embedding.py` — PEFT LoRA adapter'ı BGE-M3 üzerine ekler,
     contrastive loss ile train eder, `data/lora/bge-m3-adalet/` altına kaydeder.

Sprint-8 sonrası retrieval.embedding.Embedder LoRA adapter'ı opsiyonel yükler
(EMBEDDING_LORA_PATH env). Default OFF — Sprint-7 baseline regression-safe.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
