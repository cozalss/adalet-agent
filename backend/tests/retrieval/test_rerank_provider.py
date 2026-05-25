"""RerankProvider — Protocol + Local/Cohere/Jina factory testleri.

Cohere/Jina HTTP API'lerini çağırmıyoruz (keysiz çalışmaz). Sadece factory
seçimi + raise davranışı test edilir.
"""

from __future__ import annotations

import pytest

from retrieval import rerank_provider as rp


def test_get_provider_default_is_local(monkeypatch):
    monkeypatch.delenv("RERANK_PROVIDER", raising=False)
    rp.reset_provider()
    monkeypatch.setattr(rp, "PROVIDER", "local")
    p = rp.get_provider()
    assert p.name == "local-bge"
    assert isinstance(p, rp.LocalBGEProvider)


def test_get_provider_cohere_requires_api_key(monkeypatch):
    rp.reset_provider()
    monkeypatch.setenv("RERANK_PROVIDER", "cohere")
    monkeypatch.setattr(rp, "PROVIDER", "cohere")
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    p = rp.get_provider(name="cohere")
    assert p.name == "cohere"
    # API key yok → rerank() çağrısı raise eder
    with pytest.raises(RuntimeError, match="COHERE_API_KEY"):
        import asyncio
        asyncio.run(p.rerank("q", ["doc1", "doc2"]))


def test_get_provider_jina_requires_api_key(monkeypatch):
    rp.reset_provider()
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    p = rp.get_provider(name="jina")
    assert p.name == "jina"
    with pytest.raises(RuntimeError, match="JINA_API_KEY"):
        import asyncio
        asyncio.run(p.rerank("q", ["doc1"]))


def test_get_provider_unknown_falls_back_local(monkeypatch):
    rp.reset_provider()
    p = rp.get_provider(name="something-unknown")
    assert p.name == "local-bge"


def test_rerank_score_dataclass():
    r = rp.RerankScore(index=2, score=0.95)
    assert r.index == 2
    assert r.score == 0.95


def test_provider_singleton(monkeypatch):
    """get_provider() name=None → singleton döner."""
    rp.reset_provider()
    monkeypatch.setattr(rp, "PROVIDER", "local")
    p1 = rp.get_provider()
    p2 = rp.get_provider()
    assert p1 is p2
