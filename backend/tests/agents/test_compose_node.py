"""compose_node — intent tabanlı doğal dil üretimi + güvenli fallback."""

from __future__ import annotations

import pytest

from agents.llm import LLMResponse
from agents.nodes.compose import compose_node, redirect_to_scope_fallback


class _FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content

    async def chat(self, *_args, **_kwargs) -> LLMResponse:
        return LLMResponse(content=self.content)


@pytest.mark.asyncio
async def test_compose_redirect_uses_valid_llm_output(monkeypatch):
    expected = (
        "Bu alan için güvenilir cevap verecek şekilde tasarlanmadım. "
        "Benim ana amacım hukuki konularda, özellikle kira ve tüketici gibi "
        "alanlarda kaynaklı bilgi vermek. İstersen yaşadığın hukuki durumu anlat."
    )
    monkeypatch.setattr("agents.nodes.compose.get_llm", lambda: _FakeLLM(expected))

    out = await compose_node({
        "question": "Film önerir misin?",
        "response_intent": "redirect_to_scope",
    })

    assert out["composed_response"] == expected


@pytest.mark.asyncio
async def test_compose_redirect_accepts_natural_scope_language(monkeypatch):
    expected = (
        "Filmler konusunda tavsiyede bulunmak benim görevim dışında. "
        "Ben ADALET olarak hukuki konularda, özellikle tüketici ve kira gibi "
        "alanlarda yardımcı olabilirim."
    )
    monkeypatch.setattr("agents.nodes.compose.get_llm", lambda: _FakeLLM(expected))

    out = await compose_node({
        "question": "Film önerir misin?",
        "response_intent": "redirect_to_scope",
    })

    assert out["composed_response"] == expected


@pytest.mark.asyncio
async def test_compose_redirect_accepts_task_boundary_language(monkeypatch):
    expected = (
        "Filmler hakkında bilgi vermek benim görevim değil. "
        "Ben ADALET olarak hukuki danışmanlık kapsamında tüketici, iş ve kira "
        "gibi alanlarda yardımcı olabilirim."
    )
    monkeypatch.setattr("agents.nodes.compose.get_llm", lambda: _FakeLLM(expected))

    out = await compose_node({
        "question": "Film önerir misin?",
        "response_intent": "redirect_to_scope",
    })

    assert out["composed_response"] == expected


@pytest.mark.asyncio
async def test_compose_redirect_falls_back_for_invalid_llm_output(monkeypatch):
    monkeypatch.setattr(
        "agents.nodes.compose.get_llm",
        lambda: _FakeLLM("[MOCK] Test cevabı"),
    )

    out = await compose_node({
        "question": "2+2 kaç?",
        "response_intent": "redirect_to_scope",
    })

    assert out["composed_response"] == redirect_to_scope_fallback()


@pytest.mark.asyncio
async def test_compose_noops_for_legal_answer():
    out = await compose_node({
        "question": "Kira depozitomu alamıyorum, ne yapabilirim?",
        "response_intent": "legal_answer",
    })

    assert out == {}
