"""agents/nodes/chat.py — kırmızı-çizgi (ceza/aile) regresyon testleri.

KRİTİK (CLAUDE.md §4): out_of_scope_sensitive (ceza/aile) bir genel-sohbet
node'una düşse bile DETERMİNİSTİK 'avukata danışın' yönlendirmesi döner —
LLM'e (mock'a) bağımlı DEĞİLDİR. Bu, chat-routing'in (c50ece9) ceza/aile
sorusunu serbest-form LLM cevabına açma riskini kapatır.
"""

from __future__ import annotations

from agents.nodes.chat import chat_node


async def test_chat_node_out_of_scope_is_deterministic_advisor():
    """Ceza sorusu → triaj'ın deterministik mesajı döner; 'avukat' garanti, LLM yok."""
    advisor = (
        "Ceza hukuku konularında yardımcı olamıyorum — bu tür davalarda bir ceza "
        "avukatına başvurmanızı öneririm."
    )
    state = {
        "question": "Cinayet suçlamasıyla ilgili ne yapmalıyım?",
        "response_intent": "out_of_scope_sensitive",
        "smalltalk_response": advisor,
    }
    out = await chat_node(state)
    assert out["response"] == advisor
    assert "avukat" in out["response"].lower()
    assert out["response_intent"] == "chat"
    assert out["disclaimers"] == []
    assert out["prediction"] is None


async def test_chat_node_out_of_scope_fallback_without_triaj_message():
    """smalltalk_response eksikse bile sabit 'avukata danışın' fallback'i döner →
    kırmızı çizgi hiçbir koşulda LLM'e bağımlı kalmaz."""
    out = await chat_node({
        "question": "Boşanma davası nasıl açılır?",
        "response_intent": "out_of_scope_sensitive",
    })
    assert "avukat" in out["response"].lower()
    assert out["response_intent"] == "chat"
