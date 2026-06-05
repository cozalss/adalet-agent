"""Step-back query rewrite (1.1) — birim testleri.

LLM mock (SimpleNamespace.content) + monkeypatch get_llm/search deseni
(test_multi_query ile aynı). Hepsi opt-in: default OFF iken should_rewrite False.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from retrieval import query_rewrite as qr
from retrieval.hybrid_search import SearchResult

# --------------------------------------------------------------------------
# _parse_rewrite
# --------------------------------------------------------------------------


def test_parse_rewrite_basic():
    assert qr._parse_rewrite('{"rewrite": "kira depozito iadesi talebi"}') == "kira depozito iadesi talebi"


def test_parse_rewrite_with_fence():
    raw = '```json\n{"rewrite": "iş sözleşmesi feshi kıdem tazminatı"}\n```'
    assert qr._parse_rewrite(raw) == "iş sözleşmesi feshi kıdem tazminatı"


def test_parse_rewrite_recovers_from_surrounding_text():
    raw = 'İşte: {"rewrite": "ayıplı mal bedel iadesi"} bu kadar.'
    assert qr._parse_rewrite(raw) == "ayıplı mal bedel iadesi"


def test_parse_rewrite_invalid_returns_empty():
    assert qr._parse_rewrite("düz metin") == ""
    assert qr._parse_rewrite("") == ""
    assert qr._parse_rewrite('{"baska": "alan"}') == ""


# --------------------------------------------------------------------------
# is_query_rewrite_enabled / should_rewrite gating
# --------------------------------------------------------------------------


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("QUERY_REWRITE_ENABLED", raising=False)
    assert qr.is_query_rewrite_enabled() is False
    # konuşma-dili soru olsa bile flag kapalı → rewrite yok
    assert qr.should_rewrite("ev sahibim depozitomu vermiyor ne yapabilirim", "kira") is False


def test_should_rewrite_conversational_when_enabled(monkeypatch):
    monkeypatch.setenv("QUERY_REWRITE_ENABLED", "1")
    assert qr.should_rewrite("ev sahibim depozitomu vermiyor ne yapabilirim", "kira") is True


def test_should_not_rewrite_law_reference_query(monkeypatch):
    monkeypatch.setenv("QUERY_REWRITE_ENABLED", "1")
    # kanun-referanslı / spesifik sorgu → complexity düşük → rewrite gereksiz
    assert qr.should_rewrite("TBK madde 347 kira", "kira") is False


# --------------------------------------------------------------------------
# step_back_query (LLM mock)
# --------------------------------------------------------------------------


class _RewriteLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def chat(self, **_kwargs):
        return SimpleNamespace(content=self.payload)


class _FailingLLM:
    async def chat(self, **_kwargs):
        raise ConnectionError("llm down")


@pytest.mark.asyncio
async def test_step_back_query_returns_rewrite(monkeypatch):
    monkeypatch.setattr(
        qr, "get_llm",
        lambda: _RewriteLLM('{"rewrite": "kira sözleşmesi depozito iadesi talebi"}'),
    )
    out = await qr.step_back_query("ev sahibim depozitomu vermiyor", "kira")
    assert out == "kira sözleşmesi depozito iadesi talebi"


@pytest.mark.asyncio
async def test_step_back_query_empty_when_same_as_question(monkeypatch):
    """Rewrite orijinalle aynıysa no-op (baseline) → "" döner."""
    monkeypatch.setattr(
        qr, "get_llm", lambda: _RewriteLLM('{"rewrite": "ev sahibim depozitomu vermiyor"}'),
    )
    out = await qr.step_back_query("ev sahibim depozitomu vermiyor", "kira")
    assert out == ""


@pytest.mark.asyncio
async def test_step_back_query_empty_on_llm_failure(monkeypatch):
    """LLM çökerse "" → caller orijinalle devam eder (baseline güvenli)."""
    monkeypatch.setattr(qr, "get_llm", lambda: _FailingLLM())
    out = await qr.step_back_query("ev sahibim depozitomu vermiyor", "kira")
    assert out == ""


# --------------------------------------------------------------------------
# search_with_step_back — RRF birleştirme (search + step_back mock)
# --------------------------------------------------------------------------


def _sr(chunk_id: str) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id, score=1.0, text=f"metin {chunk_id}",
        source="mevzuat", source_url="", domain="kira", metadata={},
    )


@pytest.mark.asyncio
async def test_search_with_step_back_single_when_no_rewrite(monkeypatch):
    """Rewrite "" ise yalnız orijinal arama (baseline davranış)."""
    monkeypatch.setattr(qr, "step_back_query", lambda *_a, **_k: _async_ret(""))
    calls: list[str] = []

    async def _fake_search(question, **_kwargs):
        calls.append(question)
        return [_sr("a"), _sr("b")]

    monkeypatch.setattr(qr, "search", _fake_search)
    results, rewrite = await qr.search_with_step_back("depozito soru", domain="kira", top_k=5)
    assert rewrite == ""
    assert calls == ["depozito soru"]          # yalnız orijinal arandı
    assert [r.chunk_id for r in results] == ["a", "b"]


@pytest.mark.asyncio
async def test_search_with_step_back_rrf_merges_both(monkeypatch):
    """Rewrite varsa orijinal + rewrite ayrı aranıp RRF ile birleşir; orijinal havuzda kalır."""
    monkeypatch.setattr(qr, "step_back_query", lambda *_a, **_k: _async_ret("resmî rewrite"))

    async def _fake_search(question, **_kwargs):
        if question == "resmî rewrite":
            return [_sr("x"), _sr("a")]
        return [_sr("a"), _sr("b")]

    monkeypatch.setattr(qr, "search", _fake_search)
    results, rewrite = await qr.search_with_step_back("depozito soru", domain="kira", top_k=5)
    assert rewrite == "resmî rewrite"
    ids = {r.chunk_id for r in results}
    assert ids == {"a", "b", "x"}              # her iki kaynak havuzda (orijinal kaybolmaz)
    # "a" her iki listede → RRF en üst
    assert results[0].chunk_id == "a"


def _async_ret(value):
    async def _coro(*_a, **_k):
        return value
    return _coro()


# --------------------------------------------------------------------------
# decontextualize_for_retrieval (multi-turn konuşma takip sorusu)
# --------------------------------------------------------------------------

_HISTORY = [
    {"role": "user", "content": "kıdem tazminatı şartları nelerdir"},
    {"role": "assistant", "content": "Kıdem için en az 1 yıl çalışma gerekir [src: m-EIK-14]."},
]


def test_is_followup_markers():
    assert qr._is_followup("peki 1 yıldan az çalıştıysam ne olur") is True
    assert qr._is_followup("O zaman ne yapmalıyım") is True
    assert qr._is_followup("kıdem tazminatı şartları nelerdir") is False


def test_conv_decontext_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CONV_DECONTEXT_ENABLED", raising=False)
    assert qr.is_conv_decontext_enabled() is False


@pytest.mark.asyncio
async def test_decontext_disabled_returns_original(monkeypatch):
    monkeypatch.delenv("CONV_DECONTEXT_ENABLED", raising=False)
    out = await qr.decontextualize_for_retrieval("peki 1 yıldan azsa", _HISTORY, "isHukuku")
    assert out == "peki 1 yıldan azsa"  # kapalı → LLM çağrılmaz, orijinal


@pytest.mark.asyncio
async def test_decontext_no_history_returns_original(monkeypatch):
    monkeypatch.setenv("CONV_DECONTEXT_ENABLED", "1")
    out = await qr.decontextualize_for_retrieval("peki 1 yıldan azsa", [], "isHukuku")
    assert out == "peki 1 yıldan azsa"  # geçmiş yok → orijinal


@pytest.mark.asyncio
async def test_decontext_non_followup_returns_original(monkeypatch):
    monkeypatch.setenv("CONV_DECONTEXT_ENABLED", "1")
    out = await qr.decontextualize_for_retrieval("kıdem tazminatı şartları", _HISTORY, "isHukuku")
    assert out == "kıdem tazminatı şartları"  # marker yok → takip değil → orijinal (LLM çağrısı yok)


@pytest.mark.asyncio
async def test_decontext_rewrites_followup_with_history(monkeypatch):
    monkeypatch.setenv("CONV_DECONTEXT_ENABLED", "1")
    monkeypatch.setattr(
        qr, "get_llm",
        lambda: _RewriteLLM('{"rewrite": "1 yıldan az çalışan işçi kıdem tazminatına hak kazanır mı?"}'),
    )
    out = await qr.decontextualize_for_retrieval("peki 1 yıldan azsa", _HISTORY, "isHukuku")
    assert out == "1 yıldan az çalışan işçi kıdem tazminatına hak kazanır mı?"


@pytest.mark.asyncio
async def test_decontext_llm_failure_returns_original(monkeypatch):
    monkeypatch.setenv("CONV_DECONTEXT_ENABLED", "1")
    monkeypatch.setattr(qr, "get_llm", lambda: _FailingLLM())
    out = await qr.decontextualize_for_retrieval("peki 1 yıldan azsa", _HISTORY, "isHukuku")
    assert out == "peki 1 yıldan azsa"  # graceful → baseline


class _RuntimeFailLLM:
    """llama.cpp iç hatasını taklit (RuntimeError — _LLM_FALLBACK_EXCEPTIONS DIŞI)."""
    async def chat(self, **_kwargs):
        raise RuntimeError("llama_decode failed -1")


@pytest.mark.asyncio
async def test_decontext_broad_exception_returns_original(monkeypatch):
    """SÖZLEŞME: dar tuple dışı hata (RuntimeError) da → orijinal (retrieval boşaltılmaz)."""
    monkeypatch.setenv("CONV_DECONTEXT_ENABLED", "1")
    monkeypatch.setattr(qr, "get_llm", lambda: _RuntimeFailLLM())
    out = await qr.decontextualize_for_retrieval("peki 1 yıldan azsa", _HISTORY, "isHukuku")
    assert out == "peki 1 yıldan azsa"  # graceful → baseline (node retrieval'ı boşaltmaz)
