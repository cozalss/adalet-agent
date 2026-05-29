"""BGE-Reranker-v2-m3 wrapper — cross-encoder reranking.

Hybrid search ilk aşamada top-50 aday getirir (BM25 + dense + RRF).
Reranker bu 50 adayı tek tek query-document score'larıyla değerlendirir,
en alakalı top-5'i döndürür.

Türkçe hukuk için kritik: dense embedder "anlam benzerliği" verir,
cross-encoder gerçek "soru-belge alakası" verir → +%26-31 nDCG.

Model: BAAI/bge-reranker-v2-m3 (568M params, multilingual, ~1.1GB)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cached_property

import structlog

log = structlog.get_logger()
logger = logging.getLogger(__name__)

import os

RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
RERANKER_DEVICE = os.getenv("RERANKER_DEVICE", "auto").lower()  # auto|cuda|cpu
RERANKER_FP16 = os.getenv("RERANKER_FP16", "true").lower() == "true"
# Cross-encoder relevance alt eşiği (sigmoid 0-1). Bu skorun altındaki adaylar
# elenir → alakasız emsal/mevzuat LLM'e ve verify'a GÜRÜLTÜ olarak gitmesin
# (kapsam-dışı soruda zorlama "emsal" döndürmek yerine boş → reject, CLAUDE.md §1
# belirsizlik kuralı). Default 0.0 = KAPALI (baseline davranış birebir korunur);
# production'da örn. 0.3 ile açılır.
RERANK_SCORE_MIN = float(os.getenv("RERANK_SCORE_MIN", "0.0"))

# Cross-encoder input token TAVANI. KRİTİK PERF: BGE-reranker-v2-m3 varsayılan
# max_length 8192 token. Mevzuat corpus'unda bazı chunk'lar devasa (ölçüldü:
# 48.000 / 27.000 karakter ≈ 16K+ token — chunking artefaktı). Truncation
# olmadan cross-encoder bu dev metinleri 8192 token'a kesip O(8192²) attention
# ile CPU'da işliyor → tek mevzuat rerank'ı 665s sürüyordu (emsal 29s). 512 token
# rerank için standart + yeterli (alaka ilk pasajda belli olur); O(8192²)→O(512²)
# ~256× daha az hesap. Quality-nötr: dev chunk zaten chunking hatası, ilk 512
# token alaka sinyalini taşır. Uzun chunk'lar gerekirse RERANK_MAX_LENGTH artır.
RERANK_MAX_LENGTH = int(os.getenv("RERANK_MAX_LENGTH", "512"))


@dataclass(slots=True)
class RerankResult:
    """Reranked sonuç — orijinal payload + relevance score."""

    chunk_id: str
    score: float  # Cross-encoder relevance (0-1 sigmoid)
    text: str
    source: str
    source_url: str
    domain: str
    metadata: dict
    original_score: float  # Hybrid search'ten gelen RRF skoru


class Reranker:
    """BGE-Reranker-v2-m3 — lazy load, fp16 GPU, fallback CPU."""

    def __init__(
        self,
        model_name: str = RERANKER_MODEL,
        use_fp16: bool = RERANKER_FP16,
        device: str = RERANKER_DEVICE,
    ) -> None:
        self.model_name = model_name
        self.use_fp16 = use_fp16
        self.device = device

    @cached_property
    def _model(self):  # type: ignore[no-untyped-def]
        from sentence_transformers import CrossEncoder

        resolved = self.device
        if resolved == "auto":
            try:
                import torch
                resolved = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                resolved = "cpu"

        # CPU'da fp16 anlamsız + bazen NaN'e neden olur
        use_fp16 = self.use_fp16 and resolved != "cpu"

        logger.info(
            "reranker_loading model=%s fp16=%s device=%s (ilk seferde ~1.1 GB iner)",
            self.model_name, use_fp16, resolved,
        )
        # CrossEncoder daha stabil — FlagReranker tokenizer bug yok
        # max_length: dev chunk'ları kesip O(n²) attention patlamasını önler
        # (bkz. RERANK_MAX_LENGTH — mevzuat rerank 665s→saniyeler).
        return CrossEncoder(
            self.model_name,
            max_length=RERANK_MAX_LENGTH,
            device=resolved,
            automodel_args={"torch_dtype": "float16"} if use_fp16 else {},
            trust_remote_code=False,
        )

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 5,
    ) -> list[RerankResult]:
        """Top-N adayı cross-encoder ile yeniden sırala, top-K döndür.

        Args:
            query: Kullanıcı sorusu.
            candidates: hybrid_search.search() sonucu — SearchResult listesi
                veya dict listesi (text, chunk_id, vb. payload).
            top_k: Sonuç sayısı.
        """
        if not candidates:
            return []

        # CrossEncoder input: (query, document) tuple listesi
        pairs = [(query, _get_text(c)) for c in candidates]
        scores = self._model.predict(pairs, convert_to_numpy=True)

        # Skorları aday'larla eşle, sırala
        scored = list(zip(candidates, scores.tolist(), strict=False))
        scored.sort(key=lambda x: x[1], reverse=True)

        # Alaka eşiği (opt-in): eşik altı adayları ele. Hepsi elenirse [] döner
        # → çağıran (emsal/mevzuat) "kaynak yok" yolundan reject'e gider.
        if RERANK_SCORE_MIN > 0.0:
            scored = [(c, s) for c, s in scored if s >= RERANK_SCORE_MIN]

        return [_to_result(cand, score) for cand, score in scored[:top_k]]


def _get_text(candidate) -> str:  # type: ignore[no-untyped-def]
    """SearchResult dataclass veya dict — text field'ını al."""
    if hasattr(candidate, "text"):
        return candidate.text
    return candidate.get("text", "")


def _to_result(candidate, score: float) -> RerankResult:  # type: ignore[no-untyped-def]
    """SearchResult veya dict → RerankResult."""
    if hasattr(candidate, "chunk_id"):
        return RerankResult(
            chunk_id=candidate.chunk_id,
            score=float(score),
            text=candidate.text,
            source=candidate.source,
            source_url=candidate.source_url,
            domain=candidate.domain,
            metadata=candidate.metadata,
            original_score=candidate.score,
        )
    return RerankResult(
        chunk_id=candidate.get("chunk_id", ""),
        score=float(score),
        text=candidate.get("text", ""),
        source=candidate.get("source", ""),
        source_url=candidate.get("source_url", ""),
        domain=candidate.get("domain", ""),
        metadata={k: v for k, v in candidate.items() if k not in {"text", "chunk_id", "source", "source_url", "domain"}},
        original_score=float(candidate.get("score", 0.0)),
    )


_reranker_singleton: Reranker | None = None


def get_reranker() -> Reranker:
    """Lazy singleton — FastAPI/agent kodlarında doğrudan kullan."""
    global _reranker_singleton
    if _reranker_singleton is None:
        _reranker_singleton = Reranker()
    return _reranker_singleton
