"""retrieval/hyde.py — boş-sparse guard regresyon testleri (denetim 2026-06-04).

Mursit (dense-only) embedder sparse=([],[]) döndürür. Guard öncesi HyDE bunu KOŞULSUZ bir
boş SparseVector prefetch'ine koyup RRF füzyonunu kirletiyordu (HyDE-aktif tuketici/kira/
isHukuku domainlerinde recall'u baseline-altına düşürüyordu). Guard sonrası sparse kolu
yalnız gerçek sparse varken eklenir (hybrid_search.search ile simetrik).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import retrieval.hyde as hyde


class _Emb:
    """aencode([hypo, question]) → out.dense[i], out.sparse[i] sağlayan sahte embedder."""

    def __init__(self, sparse):
        self._sparse = sparse

    async def aencode(self, texts):
        n = len(texts)
        return SimpleNamespace(
            dense=[[0.1, 0.2, 0.3] for _ in range(n)],
            sparse=[self._sparse for _ in range(n)],
        )


class _Client:
    def __init__(self):
        self.captured_prefetch = None

    async def query_points(self, **kwargs):
        self.captured_prefetch = kwargs.get("prefetch")
        return SimpleNamespace(points=[])


async def _capture_prefetch(monkeypatch, sparse):
    async def fake_hypo(question, domain=None, max_tokens=200):
        return "hipotetik kavramsal cevap"

    client = _Client()
    monkeypatch.setattr(hyde, "generate_hypothetical", fake_hypo)
    monkeypatch.setattr(hyde, "_get_embedder", lambda: _Emb(sparse))
    monkeypatch.setattr(hyde, "get_shared_client", lambda: client)
    await hyde.search_with_hyde("ev sahibim depozitomu vermiyor", top_k=5)
    return client.captured_prefetch


@pytest.mark.asyncio
async def test_hyde_skips_empty_sparse_prefetch(monkeypatch):
    """Mursit dense-only (sparse boş) → SADECE dense prefetch (boş sparse RRF'i kirletmez)."""
    prefetch = await _capture_prefetch(monkeypatch, ([], []))
    assert len(prefetch) == 1


@pytest.mark.asyncio
async def test_hyde_includes_real_sparse_prefetch(monkeypatch):
    """Gerçek sparse (BGE-M3 gibi) varsa dense + sparse iki kol da eklenir."""
    prefetch = await _capture_prefetch(monkeypatch, ([1, 5, 9], [0.4, 0.3, 0.2]))
    assert len(prefetch) == 2
