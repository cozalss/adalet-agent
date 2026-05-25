"""BGE-M3 embedding wrapper — dense + sparse + (opsiyonel) ColBERT.

BGE-M3 tek model üç farklı arama sinyali üretir:
  - dense       (1024-dim cosine)           — anlamsal yakınlık
  - sparse      (lexical BM25-benzeri)      — anahtar kelime eşleşme
  - ColBERT     (token-level multi-vector)  — late-interaction MAX_SIM

Sprint-4: ColBERT desteği eklendi. **Sprint-4 W1**: production default ON
(`COLBERT_ENABLED=1`) — query-time toggle (`COLBERT_QUERY_ENABLED`) zaten "1"
idi ama schema/encode default "0" idi → 3. kol query'de etkisizleşmişti. Storage
maliyeti yüksek (her token 1024 float, on_disk Qdrant'a alınır), CI/test ortamı
`conftest.py` ile "0"'a override eder. Mevcut collection'a ColBERT eklemek için
reseed gerekir (bkz. `scripts/seed_mevzuat.py` + `ensure_collection` migration).

Kullanım:
    embedder = Embedder()
    out = embedder.encode(["Madde 11 nedir?", "..."], return_colbert=True)
    out.dense    → list[list[float]]                 # [N, 1024]
    out.sparse   → list[tuple[indices, values]]
    out.colbert  → list[list[list[float]]] | None    # [N, T_i, 1024]
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import cached_property

import structlog

log = structlog.get_logger()

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
USE_FP16 = os.getenv("EMBEDDING_FP16", "true").lower() == "true"
MAX_LENGTH = int(os.getenv("EMBEDDING_MAX_LENGTH", "8192"))
COLBERT_DEFAULT = os.getenv("COLBERT_ENABLED", "1").lower() in {"1", "true", "yes"}
# Device zorlama — "cuda", "cpu" veya "auto" (default). FlagEmbedding multi-process
# pool'u CPU mode'da bozulduğu için (ZeroDivisionError), explicit devices=['cpu']
# geçmek zorundayız. Production'da Qwen GPU'yu doldurur → BGE-M3 CPU'ya düşer.
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "auto").lower()


@dataclass(slots=True)
class EmbedOutput:
    """BGE-M3 üçlü çıkış. ColBERT default None — yalnız istenirse doldurulur."""

    dense: list[list[float]]
    sparse: list[tuple[list[int], list[float]]]
    colbert: list[list[list[float]]] | None = field(default=None)


class Embedder:
    """BGE-M3 lazy-loaded wrapper.

    Model ilk encode çağrısında yüklenir (~2 GB GPU / CPU RAM).
    ColBERT açıkken token başına ~1024 float ek bellek (chunk başına ~2MB).
    """

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        use_fp16: bool = USE_FP16,
        device: str = EMBEDDING_DEVICE,
    ) -> None:
        self.model_name = model_name
        self.use_fp16 = use_fp16
        self.device = device

    @cached_property
    def _model(self):
        from FlagEmbedding import BGEM3FlagModel

        # Device resolution
        resolved_device = self.device
        if resolved_device == "auto":
            try:
                import torch
                resolved_device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                resolved_device = "cpu"

        # CPU mode'da fp16 anlamsız + multi-process pool bozuk → tek-process
        use_fp16 = self.use_fp16 and resolved_device != "cpu"
        kwargs: dict = {"use_fp16": use_fp16}
        if resolved_device == "cpu":
            # FlagEmbedding ZeroDivisionError fix: explicit devices listesi
            kwargs["devices"] = ["cpu"]

        log.info(
            "model_loading",
            model=self.model_name, fp16=use_fp16, device=resolved_device,
        )
        return BGEM3FlagModel(self.model_name, **kwargs)

    def encode(
        self,
        texts: list[str],
        batch_size: int = 12,
        max_length: int = MAX_LENGTH,
        return_colbert: bool | None = None,
    ) -> EmbedOutput:
        """Metin listesini embed et.

        Args:
            texts: ham metin listesi
            batch_size: BGE-M3 iç batch
            max_length: token sınırı (default 8192)
            return_colbert: True → ColBERT vec'leri de döndür.
                            None → COLBERT_ENABLED env'ine göre.
        """
        if not texts:
            return EmbedOutput(dense=[], sparse=[], colbert=None)

        want_colbert = COLBERT_DEFAULT if return_colbert is None else return_colbert

        # encode_single_device kullanıyoruz: FlagEmbedding'in default encode()
        # Windows CPU mode'da multi-process pool deadlock yapıyor (spawn).
        # encode_single_device tek process, deterministik, async-safe.
        result = self._model.encode_single_device(
            texts,
            batch_size=batch_size,
            max_length=max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=want_colbert,
        )

        dense_arr = result["dense_vecs"]
        lexical = result["lexical_weights"]

        dense_list = [vec.tolist() for vec in dense_arr]
        sparse_list = [_lexical_to_sparse(weights) for weights in lexical]

        colbert_list: list[list[list[float]]] | None = None
        if want_colbert:
            cb = result.get("colbert_vecs", [])
            colbert_list = [[v.tolist() for v in doc_vecs] for doc_vecs in cb]

        return EmbedOutput(dense=dense_list, sparse=sparse_list, colbert=colbert_list)

    def encode_query(
        self,
        text: str,
        return_colbert: bool | None = None,
    ) -> tuple[list[float], tuple[list[int], list[float]], list[list[float]] | None]:
        """Tek sorgu embed et — (dense, sparse, colbert) tuple."""
        out = self.encode([text], batch_size=1, return_colbert=return_colbert)
        colbert = out.colbert[0] if out.colbert else None
        return out.dense[0], out.sparse[0], colbert


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
