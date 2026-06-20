"""Verify LLM-judge (opt-in OpenAI grounding) — fail-OPEN + verdict. Gerçek ağ YOK.

conftest OPENAI_API_KEY'i temizler → anahtarsız fail-open testleri deterministik.
"""

from __future__ import annotations

import pytest

import verifier.llm_judge as judge
from verifier.llm_judge import judge_grounded


class _Resp:
    def __init__(self, content: str) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


def _install_httpx(monkeypatch, content: str) -> None:
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return _Resp(content)

    monkeypatch.setattr(judge.httpx, "AsyncClient", FakeClient)


@pytest.mark.asyncio
async def test_judge_grounded_true(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    _install_httpx(monkeypatch, '{"grounded": true, "reason": "kaynaklar destekliyor"}')
    grounded, reason = await judge_grounded("Kıdem 1 yıl şartı.", ["Madde 14: en az 1 yıl"])
    assert grounded is True
    assert "destekl" in reason.lower()


@pytest.mark.asyncio
async def test_judge_grounded_false(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    _install_httpx(monkeypatch, '{"grounded": false, "reason": "kaynakta yok"}')
    grounded, reason = await judge_grounded("Uydurma madde 999.", ["Madde 14: ..."])
    assert grounded is False
    assert reason


@pytest.mark.asyncio
async def test_judge_fail_open_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    grounded, reason = await judge_grounded("x", ["kaynak"])
    assert grounded is True  # fail-OPEN: sıkılaştırma yok, baseline korunur
    assert "unavailable" in reason


@pytest.mark.asyncio
async def test_judge_fail_open_on_http_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")

    class Boom:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise RuntimeError("ağ hatası")

    monkeypatch.setattr(judge.httpx, "AsyncClient", Boom)
    grounded, _reason = await judge_grounded("x", ["kaynak"])
    assert grounded is True  # hata → fail-OPEN


@pytest.mark.asyncio
async def test_judge_skips_empty():
    grounded, reason = await judge_grounded("", ["kaynak"])
    assert grounded is True and "skipped" in reason
    grounded2, _ = await judge_grounded("cevap", [])
    assert grounded2 is True
