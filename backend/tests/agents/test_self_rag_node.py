"""Self-RAG reflection node — MockLLM tabanlı testler.

NOT: Burada `os.environ["SELF_RAG_ENABLED"]="1"` KULLANMA. Import anında process
env'i kirletir ve `build_graph()` env'i dinamik okuduğu için diğer test'lere
(ör. test_graph_e2e retry-limit) sızar → toplama sırasına bağlı flaky hata.
Etkinleştirme gereken her test zaten `monkeypatch.setattr(sr_mod, ...)` kullanır.
"""

from __future__ import annotations

import pytest

from agents.nodes import self_rag as sr_mod
from agents.nodes.self_rag import SELF_RAG_ENABLED, self_rag_node


@pytest.mark.asyncio
async def test_self_rag_disabled_returns_noop(monkeypatch, base_state):
    """SELF_RAG_ENABLED=0 → boş dict döner, state değişmez."""
    monkeypatch.setattr(sr_mod, "SELF_RAG_ENABLED", False)
    out = await self_rag_node(base_state)
    assert out == {}


@pytest.mark.asyncio
async def test_self_rag_no_draft_returns_note(monkeypatch, base_state):
    """draft_response boşsa Self-RAG çalışmaz, note döner."""
    monkeypatch.setattr(sr_mod, "SELF_RAG_ENABLED", True)
    state = {**base_state, "draft_response": ""}
    out = await self_rag_node(state)
    assert "debate_notes" in out
    assert "taslak yok" in out["debate_notes"]


@pytest.mark.asyncio
async def test_self_rag_passes_through_mock(monkeypatch, base_state):
    """MockLLM default reflection: retrieve=no, supported=yes, utility=5 → pas."""
    monkeypatch.setattr(sr_mod, "SELF_RAG_ENABLED", True)
    out = await self_rag_node(base_state)
    assert "debate_notes" in out
    # MockLLM utility=5 → retry tetiklemez
    assert out.get("debate_verdict") != "retry"


@pytest.mark.asyncio
async def test_self_rag_low_utility_triggers_retry(monkeypatch, base_state):
    """Düşük utility + reflection retrieve_yes → retry sinyali."""
    monkeypatch.setattr(sr_mod, "SELF_RAG_ENABLED", True)

    async def _low_util_llm(messages, **kw):
        from agents.llm import LLMResponse
        return LLMResponse(
            content='{"retrieve": "yes", "supported": "yes", "utility": 1, '
                    '"notes": "az faydalı"}',
        )

    class _Fake:
        chat = staticmethod(_low_util_llm)

    monkeypatch.setattr(sr_mod, "get_llm", lambda: _Fake())
    state = {**base_state, "mevzuat_refs": [], "emsal_refs": []}
    out = await self_rag_node(state)
    # supported=yes ama utility=1 → retry sinyali (current verdict pass'tan farklı)
    assert out.get("debate_verdict") == "retry"


@pytest.mark.asyncio
async def test_self_rag_unsupported_triggers_reject(monkeypatch, base_state):
    """supported=no → reject."""
    monkeypatch.setattr(sr_mod, "SELF_RAG_ENABLED", True)

    async def _unsupported_llm(messages, **kw):
        from agents.llm import LLMResponse
        return LLMResponse(
            content='{"retrieve": "yes", "supported": "no", "utility": 3, '
                    '"notes": "kaynak desteklemiyor"}',
        )

    class _Fake:
        chat = staticmethod(_unsupported_llm)

    monkeypatch.setattr(sr_mod, "get_llm", lambda: _Fake())
    out = await self_rag_node(base_state)
    assert out.get("debate_verdict") == "reject"


@pytest.mark.asyncio
async def test_self_rag_llm_failure_returns_note(monkeypatch, base_state):
    """LLM hata fırlatırsa graceful fallback (state korunur)."""
    monkeypatch.setattr(sr_mod, "SELF_RAG_ENABLED", True)

    async def _broken_llm(messages, **kw):
        raise RuntimeError("LLM timeout")

    class _Fake:
        chat = staticmethod(_broken_llm)

    monkeypatch.setattr(sr_mod, "get_llm", lambda: _Fake())
    out = await self_rag_node(base_state)
    assert "Self-RAG hata" in out["debate_notes"]


def test_self_rag_env_flag_observable():
    """Modül flag bir boolean — runtime'da monkeypatch ile değiştirilebilir."""
    assert isinstance(SELF_RAG_ENABLED, bool)


def test_self_rag_parse_reflection_handles_fence():
    """```json fence ile gelen yanıt da parse edilmeli."""
    from agents.nodes.self_rag import _parse_reflection_json
    raw = '```json\n{"retrieve":"no","supported":"yes","utility":4}\n```'
    obj = _parse_reflection_json(raw)
    assert obj["utility"] == 4
    assert obj["supported"] == "yes"


def test_self_rag_parse_reflection_invalid_fails_closed():
    """Parse hatası → fail-closed: supported=no, utility=0, retrieve=yes.

    Eski davranış (supported=yes, utility=3) parse hatasını sessizce "destekleniyor"
    olarak yorumluyordu — halüsinasyon riskini gizliyordu. Artık güvenli tarafta:
    okunamayan reflection retry/yeniden-getir sinyali üretir.
    """
    from agents.nodes.self_rag import _parse_reflection_json
    obj = _parse_reflection_json("invalid garbage")
    assert obj["retrieve"] == "yes"
    assert obj["supported"] == "no"
    assert obj["utility"] == 0
