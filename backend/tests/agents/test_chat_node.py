"""agents/nodes/chat.py — kırmızı-çizgi (ceza/aile) regresyon testleri.

KRİTİK (CLAUDE.md §4): out_of_scope_sensitive (ceza/aile) bir genel-sohbet
node'una düşse bile DETERMİNİSTİK 'avukata danışın' yönlendirmesi döner —
LLM'e (mock'a) bağımlı DEĞİLDİR. Bu, chat-routing'in (c50ece9) ceza/aile
sorusunu serbest-form LLM cevabına açma riskini kapatır.
"""

from __future__ import annotations

from agents.nodes.chat import (
    _LEGAL_REDIRECT,
    _OUT_OF_SCOPE_REFUSAL,
    _safe_or_redirect,
    chat_node,
)


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


async def test_chat_node_off_domain_no_legal_signal_is_deterministic_refusal():
    """KAPSAM-DIŞI (2026-06-15): hukuki-sinyali olmayan alan-dışı soru (yemek tarifi) →
    serbest Qwen'e BIRAKILMAZ; deterministik kapsam-reddi döner. LLM'e bağımlı değil."""
    out = await chat_node({
        "question": "Mercimek çorbası nasıl yapılır?",
        "response_intent": "redirect_to_scope",
        "domain": "unknown",
    })
    assert out["response"] == _OUT_OF_SCOPE_REFUSAL
    assert out["response_intent"] == "chat"
    assert out["disclaimers"] == []
    assert out["prediction"] is None


async def test_chat_node_unknown_with_legal_signal_soft_redirects():
    """Hukuki-sinyal taşıyan ama 8 alana atanamayan soru → durumunu açmasını isteyen
    yumuşak yönlendirme (deterministik, yine Qwen'e bırakılmaz)."""
    out = await chat_node({
        "question": "5000 TL alacağım için ne yapabilirim?",
        "response_intent": "redirect_to_scope",
        "domain": "unknown",
    })
    assert out["response"] == _LEGAL_REDIRECT
    assert out["response_intent"] == "chat"


async def test_chat_node_smalltalk_is_exempt_from_refusal():
    """Smalltalk (selam/kimsin) kapsam-reddine DÜŞMEZ → Qwen ile doğal yanıt (mock'ta
    fallback selam). Deterministik red sabitleri dönmemeli."""
    out = await chat_node({
        "question": "Selam, sen kimsin?",
        "response_intent": "smalltalk",
        "domain": "unknown",
    })
    assert out["response"] not in (_OUT_OF_SCOPE_REFUSAL, _LEGAL_REDIRECT)
    assert out["response_intent"] == "chat"
