"""OpenAIClient (bulut ana LLM) — chat / chat_stream / json / retry / get_llm routing.

Gerçek ağ YOK — httpx.AsyncClient mock'lanır. conftest OPENAI_API_KEY'i temizler.
"""

from __future__ import annotations

import httpx
import pytest

import agents.llm as llm
from agents.llm import ChatMessage, OpenAIClient, get_llm, reset_llm
from core.openai_compat import cloud_enabled, validated_base_url


class _Resp:
    def __init__(self, data: dict) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._data


class _StreamCtx:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    def raise_for_status(self) -> None:
        pass

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln


def _install_fake_httpx(monkeypatch, captured: dict, *, completion: str = "Merhaba dünya",
                        stream_deltas=("Mer", "haba")) -> None:
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def post(self, url, json=None, headers=None):
            captured.update(url=url, payload=json, headers=headers)
            return _Resp({
                "choices": [{"message": {"content": completion}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            })

        def stream(self, method, url, json=None, headers=None):
            captured.update(stream_url=url, stream_payload=json)
            lines = [f'data: {{"choices":[{{"delta":{{"content":"{d}"}}}}]}}' for d in stream_deltas]
            lines.append("data: [DONE]")
            return _StreamCtx(lines)

        async def aclose(self):
            pass

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


@pytest.mark.asyncio
async def test_chat_happy_path(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured: dict = {}
    _install_fake_httpx(monkeypatch, captured)

    r = await OpenAIClient(model="gpt-4o-mini").chat(
        [ChatMessage(role="user", content="merhaba")], max_tokens=64,
    )

    assert r.content == "Merhaba dünya"
    assert r.tokens_in == 5 and r.tokens_out == 3
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["payload"]["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_chat_json_mode_sets_response_format(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured: dict = {}
    _install_fake_httpx(monkeypatch, captured, completion='{"label":"kira"}')

    await OpenAIClient().chat([ChatMessage(role="user", content="x")], json_mode=True)
    assert captured["payload"]["response_format"] == {"type": "json_object"}

    # json_schema da json_object'a maplenir (GBNF yok)
    await OpenAIClient().chat([ChatMessage(role="user", content="x")], json_schema={"type": "object"})
    assert captured["payload"]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_chat_stream_emits_tokens(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured: dict = {}
    _install_fake_httpx(monkeypatch, captured, stream_deltas=("Mer", "haba"))
    tokens: list[str] = []

    r = await OpenAIClient().chat_stream(
        [ChatMessage(role="user", content="x")], on_token=tokens.append,
    )

    assert tokens == ["Mer", "haba"]          # token token aktı
    assert r.content == "Merhaba"             # tam içerik birikti
    assert captured["stream_payload"]["stream"] is True


@pytest.mark.asyncio
async def test_chat_retries_on_503_then_succeeds(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("asyncio.sleep", _async_noop)
    calls = {"n": 0}

    class FlakyClient:
        def __init__(self, *a, **k):
            pass

        async def post(self, url, json=None, headers=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.HTTPStatusError("503", request=None, response=_FakeStatus(503))
            return _Resp({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                          "usage": {}})

        async def aclose(self):
            pass

    monkeypatch.setattr(httpx, "AsyncClient", FlakyClient)
    r = await OpenAIClient().chat([ChatMessage(role="user", content="x")])
    assert r.content == "ok"
    assert calls["n"] == 2  # 503 → retry → başarı


@pytest.mark.asyncio
async def test_chat_no_key_raises(monkeypatch):
    captured: dict = {}
    _install_fake_httpx(monkeypatch, captured)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await OpenAIClient().chat([ChatMessage(role="user", content="x")])


def test_get_llm_openai_routing(monkeypatch):
    monkeypatch.setattr(llm, "_singleton", None)
    monkeypatch.setenv("LLM_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    reset_llm()
    assert type(get_llm()).__name__ == "OpenAIClient"
    # anahtar yoksa → mock fallback (sessiz kırılma yerine)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_llm()
    assert type(get_llm()).__name__ == "MockLLM"
    reset_llm()


def test_openai_compat_helpers(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cloud_enabled() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert cloud_enabled() is True
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    assert validated_base_url() == "https://api.openai.com/v1"
    monkeypatch.setenv("OPENAI_BASE_URL", "file:///etc/passwd")
    with pytest.raises(ValueError, match="güvensiz"):
        validated_base_url()


def test_validated_base_url_blocks_imds(monkeypatch):
    """SSRF: bulut metadata (IMDS) host'u engellenmeli."""
    monkeypatch.setenv("OPENAI_BASE_URL", "http://169.254.169.254/v1")
    with pytest.raises(ValueError, match="engellendi"):
        validated_base_url()
    # localhost proxy MEŞRU (engellenmemeli)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:8080/v1")
    assert validated_base_url() == "http://127.0.0.1:8080/v1"


@pytest.mark.asyncio
async def test_chat_401_no_retry(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("asyncio.sleep", _async_noop)
    calls = {"n": 0}

    class AuthFailClient:
        def __init__(self, *a, **k):
            pass

        async def post(self, url, json=None, headers=None):
            calls["n"] += 1
            raise httpx.HTTPStatusError("401", request=None, response=_FakeStatus(401))

        async def aclose(self):
            pass

    monkeypatch.setattr(httpx, "AsyncClient", AuthFailClient)
    with pytest.raises(httpx.HTTPStatusError):
        await OpenAIClient().chat([ChatMessage(role="user", content="x")])
    assert calls["n"] == 1  # 401 retry edilmez (kalıcı hata)


@pytest.mark.asyncio
async def test_chat_empty_choices_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class EmptyClient:
        def __init__(self, *a, **k):
            pass

        async def post(self, url, json=None, headers=None):
            return _Resp({"choices": [], "usage": {}})

        async def aclose(self):
            pass

    monkeypatch.setattr(httpx, "AsyncClient", EmptyClient)
    with pytest.raises(ValueError, match="choices boş"):
        await OpenAIClient().chat([ChatMessage(role="user", content="x")])


async def _async_noop(*_a, **_k):
    return None


class _FakeStatus:
    def __init__(self, code: int) -> None:
        self.status_code = code
