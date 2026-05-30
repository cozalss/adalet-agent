"""retrieval/speculative_search.py birim testleri.

Spekülatif arama garantisi: kullanıcı max deadline_s + baseline latans bekler.
HyDE/MQ deadline içinde biterse kaliteli sonuç döner, bitmezse hybrid fallback.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from retrieval.adaptive_router import RoutingDecision


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------

class _FakeResult:
    """SearchResult benzeri minimum stub."""
    def __init__(self, chunk_id: str, score: float = 0.9):
        self.chunk_id = chunk_id
        self.score = score
        self.text = f"metin_{chunk_id}"
        self.domain = "tuketici"
        self.source = "test"
        self.source_url = ""
        self.metadata = {}


def _routing(use_hyde: bool = False, use_mq: bool = False, domain: str = "tuketici") -> RoutingDecision:
    if use_hyde and use_mq:
        strategy = "hyde+mq"
    elif use_hyde:
        strategy = "hyde"
    elif use_mq:
        strategy = "mq"
    else:
        strategy = "hybrid"
    return RoutingDecision(use_hyde=use_hyde, use_mq=use_mq, strategy=strategy,
                           complexity=0.8, domain=domain)


# ---------------------------------------------------------------------------
# 1. Routing = hybrid → sadece hybrid çağrılır, hızlı döner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hybrid_only_when_routing_hybrid():
    hybrid_results = [_FakeResult("h1"), _FakeResult("h2")]

    with patch("retrieval.speculative_search.search", new_callable=AsyncMock) as mock_search, \
         patch("retrieval.speculative_search.search_with_hyde", new_callable=AsyncMock) as mock_hyde, \
         patch("retrieval.speculative_search.search_multi_query", new_callable=AsyncMock) as mock_mq:
        mock_search.return_value = hybrid_results
        from retrieval.speculative_search import search_speculative

        results, strategy = await search_speculative(
            question="test sorgu",
            routing=_routing(use_hyde=False, use_mq=False),
            top_k=5,
            deadline_s=2.0,
        )

    assert strategy == "hybrid"
    assert len(results) <= 5
    mock_search.assert_called_once()
    mock_hyde.assert_not_called()
    mock_mq.assert_not_called()


# ---------------------------------------------------------------------------
# 2. HyDE deadline içinde biterse → HyDE sonucu döner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hyde_wins_when_fast():
    hybrid_results = [_FakeResult("h1")]
    hyde_results = [_FakeResult("hyde1"), _FakeResult("hyde2")]

    async def _fast_hyde(*args, **kw):
        return hyde_results  # anlık

    with patch("retrieval.speculative_search.search", new_callable=AsyncMock) as mock_search, \
         patch("retrieval.speculative_search.search_with_hyde", side_effect=_fast_hyde), \
         patch("retrieval.speculative_search.search_multi_query", new_callable=AsyncMock):
        mock_search.return_value = hybrid_results
        from retrieval.speculative_search import search_speculative

        results, strategy = await search_speculative(
            question="ayıplı ürün ne yapabilirim",
            routing=_routing(use_hyde=True, use_mq=False),
            top_k=10,
            deadline_s=5.0,  # geniş bütçe
        )

    assert "hyde" in strategy
    assert any(r.chunk_id == "hyde1" for r in results)


# ---------------------------------------------------------------------------
# 3. HyDE deadline aşarsa → hybrid fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hyde_timeout_fallback_to_hybrid():
    hybrid_results = [_FakeResult("h_fallback")]

    async def _slow_hyde(*args, **kw):
        await asyncio.sleep(10)  # çok yavaş
        return [_FakeResult("hyde_never")]

    with patch("retrieval.speculative_search.search", new_callable=AsyncMock) as mock_search, \
         patch("retrieval.speculative_search.search_with_hyde", side_effect=_slow_hyde), \
         patch("retrieval.speculative_search.search_multi_query", new_callable=AsyncMock):
        mock_search.return_value = hybrid_results
        from retrieval.speculative_search import search_speculative

        results, strategy = await search_speculative(
            question="sorgu",
            routing=_routing(use_hyde=True, use_mq=False),
            top_k=10,
            deadline_s=0.01,  # çok kısa bütçe → timeout
        )

    assert strategy == "hybrid_fallback"
    assert results[0].chunk_id == "h_fallback"


# ---------------------------------------------------------------------------
# 4. MQ deadline içinde biterse → MQ sonucu döner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mq_wins_when_fast():
    hybrid_results = [_FakeResult("h1")]
    mq_results = [_FakeResult("mq1"), _FakeResult("mq2")]

    async def _fast_mq(*args, **kw):
        return mq_results

    with patch("retrieval.speculative_search.search", new_callable=AsyncMock) as mock_search, \
         patch("retrieval.speculative_search.search_with_hyde", new_callable=AsyncMock), \
         patch("retrieval.speculative_search.search_multi_query", side_effect=_fast_mq):
        mock_search.return_value = hybrid_results
        from retrieval.speculative_search import search_speculative

        results, strategy = await search_speculative(
            question="trafik kazası ne yapabilirim",
            routing=_routing(use_hyde=False, use_mq=True),
            top_k=10,
            deadline_s=5.0,
        )

    assert "mq" in strategy
    assert any(r.chunk_id == "mq1" for r in results)


# ---------------------------------------------------------------------------
# 5. Hem HyDE hem MQ → ikisi de birleşir
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_both_hyde_mq_merge():
    hybrid_results = [_FakeResult("h1")]
    hyde_results = [_FakeResult("hyde_chunk")]
    mq_results = [_FakeResult("mq_chunk")]

    async def _fast_hyde(*args, **kw):
        return hyde_results

    async def _fast_mq(*args, **kw):
        return mq_results

    with patch("retrieval.speculative_search.search", new_callable=AsyncMock) as mock_search, \
         patch("retrieval.speculative_search.search_with_hyde", side_effect=_fast_hyde), \
         patch("retrieval.speculative_search.search_multi_query", side_effect=_fast_mq):
        mock_search.return_value = hybrid_results
        from retrieval.speculative_search import search_speculative

        results, strategy = await search_speculative(
            question="depozitom geri verilmiyor ne yapabilirim",
            routing=_routing(use_hyde=True, use_mq=True),
            top_k=10,
            deadline_s=5.0,
        )

    assert "hyde" in strategy or "mq" in strategy
    ids = {r.chunk_id for r in results}
    # En az birinin sonuçları birleşmeli
    assert ids & {"hyde_chunk", "mq_chunk"}


# ---------------------------------------------------------------------------
# 6. top_k kırpma — dönen sonuç sayısı ≤ top_k
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_top_k_respected():
    many_results = [_FakeResult(f"r{i}") for i in range(50)]

    with patch("retrieval.speculative_search.search", new_callable=AsyncMock) as mock_search, \
         patch("retrieval.speculative_search.search_with_hyde", new_callable=AsyncMock), \
         patch("retrieval.speculative_search.search_multi_query", new_callable=AsyncMock):
        mock_search.return_value = many_results
        from retrieval.speculative_search import search_speculative

        results, _ = await search_speculative(
            question="sorgu",
            routing=_routing(use_hyde=False, use_mq=False),
            top_k=5,
            deadline_s=2.0,
        )

    assert len(results) <= 5


# ---------------------------------------------------------------------------
# 7. HyDE hata fırlatırsa → hybrid fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hyde_error_falls_back_to_hybrid():
    hybrid_results = [_FakeResult("safe_fallback")]

    async def _failing_hyde(*args, **kw):
        raise ConnectionError("Qdrant bağlanamadı")

    with patch("retrieval.speculative_search.search", new_callable=AsyncMock) as mock_search, \
         patch("retrieval.speculative_search.search_with_hyde", side_effect=_failing_hyde), \
         patch("retrieval.speculative_search.search_multi_query", new_callable=AsyncMock):
        mock_search.return_value = hybrid_results
        from retrieval.speculative_search import search_speculative

        results, strategy = await search_speculative(
            question="sorgu",
            routing=_routing(use_hyde=True, use_mq=False),
            top_k=10,
            deadline_s=5.0,
        )

    assert results[0].chunk_id == "safe_fallback"
    assert "hybrid" in strategy
