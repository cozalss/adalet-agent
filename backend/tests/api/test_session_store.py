"""InMemorySessionStore — multi-turn TTL + LRU testleri."""

from __future__ import annotations

import asyncio
import time

import pytest

from api.session_store import InMemorySessionStore, get_store, reset_store


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_store()


@pytest.mark.asyncio
async def test_get_empty_history_returns_list():
    s = InMemorySessionStore()
    h = await s.get_history("c1")
    assert h == []


@pytest.mark.asyncio
async def test_append_then_get_roundtrip():
    s = InMemorySessionStore()
    await s.append_turn("c1", {"role": "user", "content": "Kıdem nedir?"})
    await s.append_turn("c1", {"role": "assistant", "content": "Kıdem tazminatı..."})
    h = await s.get_history("c1")
    assert len(h) == 2
    assert h[0]["role"] == "user"
    assert h[1]["role"] == "assistant"
    # Timestamp otomatik eklenir
    assert "timestamp" in h[0]


@pytest.mark.asyncio
async def test_sliding_window_max_turns():
    s = InMemorySessionStore(max_turns=3)
    for i in range(5):
        await s.append_turn("c1", {"role": "user", "content": f"q{i}"})
    h = await s.get_history("c1")
    assert len(h) == 3
    # Son 3 — q2, q3, q4
    assert h[0]["content"] == "q2"
    assert h[-1]["content"] == "q4"


@pytest.mark.asyncio
async def test_clear_removes_session():
    s = InMemorySessionStore()
    await s.append_turn("c1", {"role": "user", "content": "Test"})
    await s.clear("c1")
    h = await s.get_history("c1")
    assert h == []


@pytest.mark.asyncio
async def test_session_isolation():
    """İki conversation_id birbirinden bağımsız."""
    s = InMemorySessionStore()
    await s.append_turn("c1", {"role": "user", "content": "session1"})
    await s.append_turn("c2", {"role": "user", "content": "session2"})
    h1 = await s.get_history("c1")
    h2 = await s.get_history("c2")
    assert h1[0]["content"] == "session1"
    assert h2[0]["content"] == "session2"


@pytest.mark.asyncio
async def test_ttl_expires_old_sessions(monkeypatch):
    s = InMemorySessionStore(ttl_s=1)
    await s.append_turn("c1", {"role": "user", "content": "old"})
    # Time'ı 2 saniye ileri sar — TTL aşılsın
    real_time = time.time
    monkeypatch.setattr("api.session_store.time.time", lambda: real_time() + 2.0)
    h = await s.get_history("c1")
    assert h == []


@pytest.mark.asyncio
async def test_max_sessions_evicts_lru():
    s = InMemorySessionStore(max_sessions=3)
    for i in range(5):
        await s.append_turn(f"c{i}", {"role": "user", "content": "x"})
    # c0 ve c1 evict edildi
    h0 = await s.get_history("c0")
    h4 = await s.get_history("c4")
    assert h0 == []
    assert len(h4) == 1


@pytest.mark.asyncio
async def test_get_store_singleton():
    s1 = get_store()
    s2 = get_store()
    assert s1 is s2


@pytest.mark.asyncio
async def test_health_always_true_for_memory():
    s = InMemorySessionStore()
    assert await s.health() is True


@pytest.mark.asyncio
async def test_concurrent_appends_dont_lose_turns():
    """Async race condition basit testi."""
    s = InMemorySessionStore(max_turns=20)
    await asyncio.gather(*[
        s.append_turn("c1", {"role": "user", "content": f"q{i}"})
        for i in range(10)
    ])
    h = await s.get_history("c1")
    assert len(h) == 10
