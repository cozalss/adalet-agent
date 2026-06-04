"""Canlı emsal fallback (CRAG) — birim testleri (network YOK, mock client+reranker).

Lokal corpus zayıfsa internetten dava cek + LOKAL rerank. Opt-in (default 0).
"""

from __future__ import annotations

import pytest

from retrieval import live_emsal as le
from retrieval.reranker import RerankResult
from retrieval.yargi_client import RegulatorDecision, YargitayDecision


class _FakeReranker:
    """rerank(q, cands, top_k) → skoru indeks-azalan RerankResult (mock relevance)."""

    def rerank(self, q, cands, top_k):
        out = []
        for i, c in enumerate(cands[:top_k]):
            out.append(RerankResult(
                chunk_id=c["chunk_id"], score=0.9 - i * 0.3, text=c["text"],
                source=c["source"], source_url=c["source_url"],
                domain=c.get("domain", ""), metadata={}, original_score=0.0,
            ))
        return out


class _FakeYargi:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def search_sigorta_tahkim(self, q, page=1):
        return [
            RegulatorDecision("sigorta_tahkim", "s1", "Kaza kararı", "2024", None,
                              "trafik kazası kusur oranı tespiti tazminat", "http://x/s1"),
            RegulatorDecision("sigorta_tahkim", "s2", "Hasar", "2024", None,
                              "alakasız metin sigorta poliçe", "http://x/s2"),
        ]

    async def search_yargitay(self, q, page_size=10):
        return [YargitayDecision("y1", "YARGITAYKARARI", None, "Karar", "2024", None,
                                 "", "http://x/y1")]

    async def get_document(self, doc_id):
        return "yargıtay tam metin trafik tazminat"


@pytest.mark.asyncio
async def test_fetch_and_rank_live_returns_reranked(monkeypatch):
    monkeypatch.setattr("retrieval.yargi_client.YargiClient", lambda *_a, **_k: _FakeYargi())
    monkeypatch.setattr(le, "get_reranker", lambda: _FakeReranker())
    out = await le.fetch_and_rank_live("trafik kazası tazminat", "trafik", top_k=5, min_score=0.30)
    assert out, "canlı aday dönmeli"
    assert out[0].metadata.get("live") is True
    assert out[0].score >= 0.30
    # min_score altı elenmeli (0.9, 0.6 kalır; 0.3 sinirda; <0.3 elenir)
    assert all(r.score >= 0.30 for r in out)


@pytest.mark.asyncio
async def test_fetch_and_rank_live_empty_on_client_failure(monkeypatch):
    class _Boom:
        async def __aenter__(self):
            raise ConnectionError("yargi-mcp down")
        async def __aexit__(self, *_a):
            return False
    monkeypatch.setattr("retrieval.yargi_client.YargiClient", lambda *_a, **_k: _Boom())
    monkeypatch.setattr(le, "get_reranker", lambda: _FakeReranker())
    out = await le.fetch_and_rank_live("trafik kazası", "trafik")
    assert out == []  # network hatası → [] (çağıran corpus ile devam eder)


@pytest.mark.asyncio
async def test_fetch_and_rank_live_filters_below_min_score(monkeypatch):
    monkeypatch.setattr("retrieval.yargi_client.YargiClient", lambda *_a, **_k: _FakeYargi())
    monkeypatch.setattr(le, "get_reranker", lambda: _FakeReranker())
    # min_score yüksek → hicbiri kabul edilmez → [] (dürüst 'bulunamadı')
    out = await le.fetch_and_rank_live("trafik", "trafik", top_k=5, min_score=0.99)
    assert out == []
