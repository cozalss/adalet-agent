"""Smalltalk (sohbet) tespiti + triaj/finalize entegrasyonu testleri.

Selamlaşma/teşekkür/"ne yaparsın" girdileri:
  - LLM çağırmadan tespit edilmeli (anında),
  - finalize'da soğuk ret yerine dostça hazır yanıt dönmeli,
  - hukuki disclaimer içermemeli (hukuki iddia yok),
  - selamla başlayan GERÇEK hukuk soruları smalltalk SAYILMAMALI.
"""

from __future__ import annotations

import pytest

from agents.nodes.finalize import finalize_node
from agents.nodes.triaj import triaj_node
from agents.smalltalk import detect_smalltalk, smalltalk_reply


# --- Tespit: pozitif (saf sohbet) ---
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("merhaba", "greeting"),
        ("Merhaba!", "greeting"),
        ("MERHABA", "greeting"),
        ("selam", "greeting"),
        ("İyi günler", "greeting"),
        ("günaydın", "greeting"),
        ("merhaba dostum", "greeting"),
        ("teşekkürler", "thanks"),
        ("teşekkür ederim", "thanks"),
        ("sağ ol", "thanks"),
        ("görüşürüz", "farewell"),
        ("hoşça kal", "farewell"),
        ("ne yapabilirsin", "capability"),
        ("neler yapabilirsin?", "capability"),
        ("kimsin", "identity"),
        ("sen kimsin?", "identity"),
    ],
)
def test_detect_smalltalk_positive(text: str, expected: str) -> None:
    assert detect_smalltalk(text) == expected


# --- Tespit: negatif (gerçek hukuk sorusu None dönmeli) ---
@pytest.mark.parametrize(
    "text",
    [
        "Kira depozitomu ev sahibi iade etmiyor, ne yapabilirim?",
        "merhaba kira sözleşmem hakkında bir sorum var",
        "selam, işten çıkarıldım tazminat alabilir miyim",
        "iyi günler 3 aydır maaşımı alamıyorum ne yapmalıyım",
        "ayıplı mal aldım iade hakkım var mı",
        "merhaba madde 11 nedir",
        "",
        "   ",
    ],
)
def test_detect_smalltalk_negative(text: str) -> None:
    assert detect_smalltalk(text) is None


def test_smalltalk_reply_nonempty_for_each_category() -> None:
    for cat in ("greeting", "thanks", "farewell", "capability", "identity"):
        reply = smalltalk_reply(cat)
        assert reply.strip()
        # Sohbet yanıtı SOMUT hukuki iddia (madde/karar numarası) içermemeli.
        assert "Madde" not in reply
        assert "Yargıtay 1" not in reply


def test_smalltalk_reply_unknown_category_falls_back() -> None:
    assert smalltalk_reply("bilinmeyen") == smalltalk_reply("greeting")


# --- Triaj entegrasyonu: LLM ÇAĞRILMADAN smalltalk_response set edilmeli ---
@pytest.mark.asyncio
async def test_triaj_smalltalk_skips_llm() -> None:
    """'merhaba' → triaj LLM'i hiç çağrılmamalı, smalltalk_response set olmalı."""
    out = await triaj_node({"question": "merhaba", "chat_history": []})
    assert out["domain"] == "unknown"
    assert out.get("smalltalk_response")
    assert "ADALET" in out["smalltalk_response"]


@pytest.mark.asyncio
async def test_triaj_smalltalk_skipped_when_history_exists() -> None:
    """Konuşma ortasındaki 'teşekkürler' yeni soru akışını kesmemeli (geçmiş varsa
    smalltalk kısa-yolu atlanır → normal triaj). Mock LLM ile domain çözülür."""
    out = await triaj_node({
        "question": "teşekkürler",
        "chat_history": [{"role": "user", "content": "kira sorusu", "domain": "kira"}],
    })
    # smalltalk atlandı (geçmiş var) → normal triaj çalıştı, smalltalk_response YOK.
    assert "smalltalk_response" not in out


# --- Finalize entegrasyonu: dostça yanıt, disclaimer YOK ---
@pytest.mark.asyncio
async def test_finalize_returns_smalltalk_without_disclaimer(base_state) -> None:
    state = {**base_state, "domain": "unknown", "smalltalk_response": "Merhaba! Ben ADALET."}
    out = await finalize_node(state)
    assert out["response"] == "Merhaba! Ben ADALET."
    assert out["disclaimers"] == []          # sohbette hukuki disclaimer yok
    assert "avukata danışın" not in out["response"].lower()  # soğuk ret değil
    assert out["confidence"] == 1.0


@pytest.mark.asyncio
async def test_finalize_out_of_scope_sensitive_is_reject_not_smalltalk(base_state) -> None:
    state = {
        **base_state,
        "domain": "unknown",
        "response_intent": "out_of_scope_sensitive",
        "smalltalk_response": "Ceza hukuku konularında yardımcı olamıyorum.",
    }
    out = await finalize_node(state)
    assert out["response"] == "Ceza hukuku konularında yardımcı olamıyorum."
    assert out["confidence"] == 0.0
    assert out["debate_verdict"] == "reject"
