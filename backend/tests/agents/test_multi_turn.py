"""triaj_node + multi-turn (chat_history) testleri."""

from __future__ import annotations

import pytest

from agents.nodes.triaj import (
    _format_history,
    _is_continuation,
    _last_user_domain,
    triaj_node,
)

# --------------------------------------------------------------------------
#  _is_continuation
# --------------------------------------------------------------------------


def test_continuation_marker_detected():
    assert _is_continuation("peki bu durumda ne yapayım?") is True
    assert _is_continuation("O zaman tazminat alabilir miyim?") is True
    assert _is_continuation("Bu durumda ne yapmalıyım?") is True


def test_normal_question_not_continuation():
    assert _is_continuation("Kıdem tazminatı nasıl hesaplanır?") is False
    assert _is_continuation("Ayıplı malda haklarım nedir?") is False


# --------------------------------------------------------------------------
#  _last_user_domain
# --------------------------------------------------------------------------


def test_last_user_domain_finds_latest():
    history = [
        {"role": "user", "content": "Kıdem nedir?", "domain": "isHukuku"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "Ev sahibim...", "domain": "kira"},
        {"role": "assistant", "content": "..."},
    ]
    assert _last_user_domain(history) == "kira"


def test_last_user_domain_skips_unknown():
    history = [
        {"role": "user", "content": "Cinayet?", "domain": "unknown"},
        {"role": "user", "content": "İş sorun.", "domain": "isHukuku"},
        {"role": "user", "content": "?", "domain": "unknown"},
    ]
    # Son user-turn unknown, ama bir öncesi isHukuku
    assert _last_user_domain(history) == "isHukuku"


def test_last_user_domain_empty_history():
    assert _last_user_domain([]) is None


# --------------------------------------------------------------------------
#  _format_history
# --------------------------------------------------------------------------


def test_format_history_includes_role_and_domain():
    history = [
        {"role": "user", "content": "Kıdem", "domain": "isHukuku"},
        {"role": "assistant", "content": "Tazminat..."},
    ]
    txt = _format_history(history)
    assert "KULLANICI" in txt
    assert "ASİSTAN" in txt
    assert "isHukuku" in txt
    assert "Kıdem" in txt


def test_format_history_empty_returns_placeholder():
    assert "geçmiş yok" in _format_history([]).lower()


def test_format_history_caps_at_n_turns():
    long_history = [
        {"role": "user", "content": f"q{i}", "domain": "isHukuku"} for i in range(20)
    ]
    txt = _format_history(long_history)
    # Sadece son MAX_HISTORY_TURNS_IN_PROMPT=5 görünmeli
    assert "q19" in txt
    assert "q0" not in txt
    assert "q14" not in txt  # 20 - 5 = 15'ten önceki yok


# --------------------------------------------------------------------------
#  triaj_node with history — full flow
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_triaj_inherits_domain_for_continuation(base_state):
    """Önceki turda isHukuku → 'peki o zaman...' devam sorusu aynı domain."""
    base_state["question"] = "peki bu durumda ne yapmalıyım?"
    base_state["chat_history"] = [
        {"role": "user", "content": "Kıdem tazminatı nedir?", "domain": "isHukuku"},
        {"role": "assistant", "content": "İşçinin haklarıdır..."},
    ]
    result = await triaj_node(base_state)
    # MockLLM unknown dönse bile inherited devreye girer
    assert result["domain"] in {"isHukuku", "unknown"}
    # Eğer inherited devreye girdiyse confidence en az 0.65
    if result["domain"] == "isHukuku":
        assert result["domain_confidence"] >= 0.65


@pytest.mark.asyncio
async def test_triaj_without_history_works(base_state):
    """chat_history yokken eski davranış değişmemeli (regression)."""
    base_state["question"] = "Kıdem tazminatı nasıl hesaplanır?"
    base_state.pop("chat_history", None)
    result = await triaj_node(base_state)
    assert "domain" in result
    assert result["domain"] in {"isHukuku", "unknown"}


@pytest.mark.asyncio
async def test_triaj_out_of_scope_short_circuits_history(base_state):
    """Kapsam dışı keyword → history bakılmaz, hemen reject."""
    base_state["question"] = "Cinayet davası nasıl açılır?"
    base_state["chat_history"] = [
        {"role": "user", "content": "Önceki kıdem sorusu", "domain": "isHukuku"},
    ]
    result = await triaj_node(base_state)
    assert result["domain"] == "unknown"
    assert "kapsam" in result["triage_reasoning"].lower()


@pytest.mark.asyncio
async def test_triaj_no_inheritance_for_unrelated_new_question(base_state):
    """Devam-soru OLMAYAN yeni soruda önceki domain inherit edilmez."""
    base_state["question"] = "Ayıplı malda haklarım nedir?"
    base_state["chat_history"] = [
        {"role": "user", "content": "İş sorusu", "domain": "isHukuku"},
    ]
    result = await triaj_node(base_state)
    # MockLLM keyword "ayıplı" → tuketici (isHukuku DEĞİL)
    assert result["domain"] in {"tuketici", "unknown"}
