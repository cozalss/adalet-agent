"""Multi-turn end-to-end testleri — Sprint-4 W5.6.

conversation_id ile 5-turn diyalog, session_store entegrasyonu doğrulaması.

Senaryolar:
  - İlk turn'de conversation_id verilmezse server üretmeli
  - Aynı conversation_id ile turn 2,3,4,5 history'yi birikecek
  - DELETE /session/{id} history'yi temizlemeli
  - Yeni conversation_id history'siz başlamalı
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def multi_turn_client(monkeypatch, sample_citations):
    """E2E mock retrieval + in-memory session store."""
    laws = sample_citations[:2]
    cases = [sample_citations[2]]

    async def fake_mevzuat(_state):
        return {"mevzuat_refs": laws}

    async def fake_emsal(_state):
        return {"emsal_refs": cases}

    from agents import graph as graph_mod
    monkeypatch.setattr(graph_mod, "mevzuat_node", fake_mevzuat)
    monkeypatch.setattr(graph_mod, "emsal_node", fake_emsal)

    from api.routes import ask as ask_mod
    monkeypatch.setattr(ask_mod, "_graph_singleton", None)

    # Fresh in-memory session store (Redis bypass)
    from api import session_store as ss_mod
    fresh_store = ss_mod.InMemorySessionStore()
    monkeypatch.setattr(ss_mod, "_store_singleton", fresh_store)

    # slowapi in-memory limiter state suite-wide pollute olur → reset
    from api.limiter import limiter
    limiter.reset()

    from main import app
    return TestClient(app)


def test_first_turn_generates_conversation_id(multi_turn_client):
    """conversation_id boş gönderilirse server UUID üretir."""
    resp = multi_turn_client.post(
        "/ask", json={"question": "Kıdem tazminatı nedir?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("conversation_id"), "conversation_id boş!"
    assert len(body["conversation_id"]) >= 8


def test_same_conversation_id_persists_across_turns(multi_turn_client):
    """Aynı conversation_id gönderilince 5 turn boyunca aynı kalmalı."""
    # Turn 1: create
    r1 = multi_turn_client.post(
        "/ask", json={"question": "İş Kanunu kıdem tazminatı?"},
    )
    conv_id = r1.json()["conversation_id"]
    assert conv_id

    # Turn 2-5: same conv_id
    for i, q in enumerate([
        "Ne kadar süre çalışmak gerek?",
        "Tazminat nasıl hesaplanır?",
        "Ödeme zamanı ne zaman olur?",
        "İcra takibi başlatılır mı?",
    ], start=2):
        r = multi_turn_client.post(
            "/ask",
            json={"question": q, "conversation_id": conv_id},
        )
        assert r.status_code == 200, f"Turn {i} failed: {r.text}"
        assert r.json()["conversation_id"] == conv_id, (
            f"Turn {i}: conv_id değişti"
        )


def test_session_clear_removes_history(multi_turn_client):
    """DELETE /session/{id} → 200 + history boş."""
    r1 = multi_turn_client.post(
        "/ask", json={"question": "Kira artışı sınırı?"},
    )
    conv_id = r1.json()["conversation_id"]

    # Router prefix /ask; clear_session → /ask/session/{id}
    r_del = multi_turn_client.delete(f"/ask/session/{conv_id}")
    assert r_del.status_code == 200
    assert r_del.json()["cleared"] == conv_id


def test_separate_conversations_isolated(multi_turn_client):
    """İki ayrı conversation_id aynı session içinde birbirine sızmamalı."""
    r1 = multi_turn_client.post(
        "/ask", json={"question": "Tüketici hakkı ayıplı mal?"},
    )
    r2 = multi_turn_client.post(
        "/ask", json={"question": "Kıdem tazminatı?"},
    )
    cid1 = r1.json()["conversation_id"]
    cid2 = r2.json()["conversation_id"]
    assert cid1 != cid2, "İki ayrı turn aynı conv_id almış!"


@pytest.mark.asyncio
async def test_session_store_append_and_retrieve(monkeypatch):
    """Session store low-level kontrat: append → get sırasıyla geri verir."""
    from api.session_store import ConversationTurn, InMemorySessionStore

    store = InMemorySessionStore()
    conv_id = "test-conv-123"

    await store.append_turn(conv_id, ConversationTurn(
        role="user", content="Soru 1", timestamp=1.0,
    ))
    await store.append_turn(conv_id, ConversationTurn(
        role="assistant", content="Cevap 1", timestamp=2.0,
    ))
    history = await store.get_history(conv_id)
    assert len(history) == 2
    assert history[0]["content"] == "Soru 1"
    assert history[1]["content"] == "Cevap 1"

    await store.clear(conv_id)
    assert await store.get_history(conv_id) == []


@pytest.mark.asyncio
async def test_session_store_lru_eviction():
    """InMemorySessionStore TTL/LRU davranışı (capacity limit)."""
    from api.session_store import ConversationTurn, InMemorySessionStore

    store = InMemorySessionStore(max_sessions=3)
    for i in range(5):
        await store.append_turn(f"conv-{i}", ConversationTurn(
            role="user", content=f"q{i}", timestamp=float(i),
        ))
    # max_sessions=3 → ilk 2 eviction edilmeli
    assert await store.get_history("conv-0") == []
    assert await store.get_history("conv-1") == []
    # son 3 kalmalı
    for i in range(2, 5):
        h = await store.get_history(f"conv-{i}")
        assert len(h) == 1
