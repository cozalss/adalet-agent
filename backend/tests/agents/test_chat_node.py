"""agents/nodes/chat.py — kırmızı-çizgi (ceza/aile) regresyon testleri.

KRİTİK (CLAUDE.md §4): out_of_scope_sensitive (ceza/aile) bir genel-sohbet
node'una düşse bile DETERMİNİSTİK 'avukata danışın' yönlendirmesi döner —
LLM'e (mock'a) bağımlı DEĞİLDİR. Bu, chat-routing'in (c50ece9) ceza/aile
sorusunu serbest-form LLM cevabına açma riskini kapatır.
"""

from __future__ import annotations

from agents.nodes.chat import _LEGAL_REDIRECT, _safe_or_redirect, chat_node


def test_chat_safe_or_redirect_blocks_fabricated_legal_claim():
    """KIRMIZI ÇİZGİ (denetim 2026-06-04): düşük-güven hukuki soru verify'ı atlayıp chat'e
    düşse bile, serbest-form çıktı uydurma kanun adı/eşik içerirse deterministik veto
    devreye girer → uydurma iddia final cevaba ULAŞMAZ."""
    risky = "İşçilik Kanunu'na göre 5 yıldan az çalışan kıdem tazminatı alamaz."
    assert _safe_or_redirect(risky) == _LEGAL_REDIRECT


def test_chat_safe_or_redirect_passes_clean_general_answer():
    """Genel/güvenli sohbet cevabı (uydurma hukuki kalıp yok) aynen geçer → akıcılık korunur."""
    clean = "Fransa'nın başkenti Paris'tir. Başka bir konuda yardımcı olabilir miyim?"
    assert _safe_or_redirect(clean) == clean


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
