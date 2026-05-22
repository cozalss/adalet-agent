"""BGE-M3 embedding wrapper — dense + sparse (lexical) çıktı.

BGE-M3 multilingual, Türkçe için iyi. Tek model hem dense (1024-dim cosine)
hem sparse (BM25-benzeri lexical weights) üretir → tek pass'te hybrid retrieval
için her şey hazır.

Kullanım:
    embedder = Embedder()
    out = embedder.encode(["Madde 11 nedir?", "Tüketici hakları..."])
    out["dense"]   → list[list[float]]
    out["sparse"]  → list[tuple[list[int], list[float]]]  # (indices, values)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property

import structlog

log = structlog.get_logger()

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
USE_FP16 = os.getenv("EMBEDDING_FP16", "true").lower() == "true"
MAX_LENGTH = int(os.getenv("EMBEDDING_MAX_LENGTH", "8192"))


@dataclass(slots=True)
class EmbedOutput:
    dense: list[list[float]]
    sparse: list[tuple[list[int], list[float]]]


class Embedder:
    """BGE-M3 lazy-loaded wrapper.

    Model ilk encode çağrısında yüklenir (~2 GB GPU / CPU RAM).
    """

    def __init__(self, model_name: str = MODEL_NAME, use_fp16: bool = USE_FP16) -> None:
        self.model_name = model_name
        self.use_fp16 = use_fp16

    @cached_property
    def _model(self):
        from FlagEmbedding import BGEM3FlagModel

        log.info("model_loading", model=self.model_name, fp16=self.use_fp16)
        return BGEM3FlagModel(self.model_name, use_fp16=self.use_fp16)

    def encode(
        self,
        texts: list[str],
        batch_size: int = 12,
        max_length: int = MAX_LENGTH,
    ) -> EmbedOutput:
        if not texts:
            return EmbedOutput(dense=[], sparse=[])

        result = self._model.encode(
            texts,
            batch_size=batch_size,
            max_length=max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )

        dense_arr = result["dense_vecs"]
        lexical = result["lexical_weights"]

        dense_list = [vec.tolist() for vec in dense_arr]
        sparse_list = [_lexical_to_sparse(weights) for weights in lexical]

        return EmbedOutput(dense=dense_list, sparse=sparse_list)

    def encode_query(self, text: str) -> tuple[list[float], tuple[list[int], list[float]]]:
        """Tek bir sorgu metnini embed et — convenience wrapper."""
        out = self.encode([text], batch_size=1)
        return out.dense[0], out.sparse[0]


def _lexical_to_sparse(weights: dict) -> tuple[list[int], list[float]]:
    """BGE-M3 lexical_weights (token_id_str → float) → Qdrant sparse format."""
    indices: list[int] = []
    values: list[float] = []
    for token_id_str, weight in weights.items():
        if float(weight) <= 0:
            continue
        indices.append(int(token_id_str))
        values.append(float(weight))
    return indices, values
