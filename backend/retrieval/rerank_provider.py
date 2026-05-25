"""Rerank Provider Protocol — A/B test ve sağlayıcı bağımsızlığı.

Mevcut: BAAI/bge-reranker-v2-m3 (lokal, sentence-transformers)
Opsiyonel: Cohere rerank-v3, Jina rerank v2 (HTTP API, gerek varsa)

Hangi sağlayıcı kullanılacağı `RERANK_PROVIDER` env'iyle seçilir:
    RERANK_PROVIDER=local   (default)   — BAAI/bge-reranker-v2-m3
    RERANK_PROVIDER=cohere              — COHERE_API_KEY zorunlu
    RERANK_PROVIDER=jina                — JINA_API_KEY zorunlu

Production'da OpenAI/Anthropic API kesinlikle yasak (CLAUDE.md §3) AMA
rerank için Cohere/Jina ECHO test edilebilir (A/B benchmark amacıyla).
Production deploy local kalır. Provider seçimi CI/eval içindir, runtime'da
local default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import structlog

log = structlog.get_logger()

PROVIDER = os.getenv("RERANK_PROVIDER", "local").lower()


@dataclass(slots=True)
class RerankScore:
    """Tek bir aday — relevance skoru + orijinal index (input listesi içindeki)."""

    index: int
    score: float


class RerankProvider(Protocol):
    """Tüm sağlayıcılar bu protokole bağlanır."""

    name: str

    async def rerank(
        self, query: str, docs: list[str], top_k: int = 5,
    ) -> list[RerankScore]: ...


# --------------------------------------------------------------------------
#  Local BGE — mevcut implementasyon adapter'ı
# --------------------------------------------------------------------------

class LocalBGEProvider:
    """retrieval/reranker.py:Reranker'ı protocol arkasına saran adapter."""

    name = "local-bge"

    async def rerank(
        self, query: str, docs: list[str], top_k: int = 5,
    ) -> list[RerankScore]:
        import asyncio

        from .reranker import get_reranker

        reranker = get_reranker()
        # CrossEncoder.predict CPU/GPU-bound — to_thread
        pairs = [(query, d) for d in docs]

        def _do() -> list[RerankScore]:
            scores = reranker._model.predict(pairs, convert_to_numpy=True)
            scored = list(enumerate(scores.tolist()))
            scored.sort(key=lambda x: x[1], reverse=True)
            return [RerankScore(index=i, score=float(s)) for i, s in scored[:top_k]]

        return await asyncio.to_thread(_do)


# --------------------------------------------------------------------------
#  Cohere — opsiyonel HTTP sağlayıcı (eval / A/B için)
# --------------------------------------------------------------------------

class CohereProvider:
    """Cohere rerank-v3 API.

    COHERE_API_KEY env'inden anahtar alınır. Production'da kullanılmaz —
    sadece eval/ablation için.
    """

    name = "cohere"

    def __init__(self, model: str = "rerank-multilingual-v3.0") -> None:
        self.model = model
        self.api_key = os.getenv("COHERE_API_KEY") or ""

    async def rerank(
        self, query: str, docs: list[str], top_k: int = 5,
    ) -> list[RerankScore]:
        if not self.api_key:
            raise RuntimeError("CohereProvider: COHERE_API_KEY env yok")

        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.cohere.com/v1/rerank",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "query": query,
                    "documents": docs,
                    "top_n": top_k,
                    "return_documents": False,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        return [
            RerankScore(index=r["index"], score=float(r["relevance_score"]))
            for r in payload.get("results", [])
        ]


# --------------------------------------------------------------------------
#  Jina — opsiyonel HTTP sağlayıcı
# --------------------------------------------------------------------------

class JinaProvider:
    """Jina rerank v2 (multilingual). JINA_API_KEY env."""

    name = "jina"

    def __init__(self, model: str = "jina-reranker-v2-base-multilingual") -> None:
        self.model = model
        self.api_key = os.getenv("JINA_API_KEY") or ""

    async def rerank(
        self, query: str, docs: list[str], top_k: int = 5,
    ) -> list[RerankScore]:
        if not self.api_key:
            raise RuntimeError("JinaProvider: JINA_API_KEY env yok")

        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.jina.ai/v1/rerank",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                },
                json={
                    "model": self.model,
                    "query": query,
                    "documents": docs,
                    "top_n": top_k,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        return [
            RerankScore(index=r["index"], score=float(r["relevance_score"]))
            for r in payload.get("results", [])
        ]


# --------------------------------------------------------------------------
#  Factory + singleton
# --------------------------------------------------------------------------

_provider_singleton: RerankProvider | None = None


def get_provider(name: str | None = None) -> RerankProvider:
    """Provider singleton. `name` override (test/eval için)."""
    global _provider_singleton
    if name is None and _provider_singleton is not None:
        return _provider_singleton

    chosen = (name or PROVIDER).lower()
    if chosen == "cohere":
        provider: RerankProvider = CohereProvider()
    elif chosen == "jina":
        provider = JinaProvider()
    else:
        provider = LocalBGEProvider()

    if name is None:
        _provider_singleton = provider
    log.info("rerank_provider_loaded", name=provider.name)
    return provider


def reset_provider() -> None:
    """Test fixture — singleton sıfırla."""
    global _provider_singleton
    _provider_singleton = None


__all__ = (
    "CohereProvider",
    "JinaProvider",
    "LocalBGEProvider",
    "RerankProvider",
    "RerankScore",
    "get_provider",
    "reset_provider",
)
