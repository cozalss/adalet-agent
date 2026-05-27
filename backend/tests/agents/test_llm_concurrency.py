"""agents/llm.py — LlamaCppClient eşzamanlı model-load race koruması (W21).

Lock olmadan iki eşzamanlı chat() çağrısı modeli İKİ KEZ yükler (çift GPU
bellek → OOM). Double-checked asyncio.Lock ile tek load garanti edilir.
torch/llama_cpp YÜKLENMEZ — _load monkeypatch'lenir (mock).
"""

from __future__ import annotations

import asyncio
import time

import pytest

from agents.llm import ChatMessage, LlamaCppClient


class _FakeModel:
    def create_chat_completion(self, **_kwargs):
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }


@pytest.mark.asyncio
async def test_concurrent_chat_loads_model_once(monkeypatch):
    client = LlamaCppClient(model_path="/fake/path.gguf")
    load_calls = {"n": 0}

    def fake_load():
        load_calls["n"] += 1
        time.sleep(0.05)  # yükleme penceresini genişlet (worker thread)
        return _FakeModel()

    monkeypatch.setattr(client, "_load", fake_load)

    msgs = [ChatMessage(role="user", content="merhaba")]
    results = await asyncio.gather(
        client.chat(msgs), client.chat(msgs), client.chat(msgs),
    )

    # Lock sayesinde 3 eşzamanlı çağrı modeli TEK KEZ yükler.
    assert load_calls["n"] == 1
    assert all(r.content == "ok" for r in results)


@pytest.mark.asyncio
async def test_second_call_skips_load(monkeypatch):
    """Model yüklendikten sonra ikinci çağrı tekrar yüklemez (lock alınmaz)."""
    client = LlamaCppClient(model_path="/fake/path.gguf")
    load_calls = {"n": 0}

    def fake_load():
        load_calls["n"] += 1
        return _FakeModel()

    monkeypatch.setattr(client, "_load", fake_load)
    msgs = [ChatMessage(role="user", content="x")]
    await client.chat(msgs)
    await client.chat(msgs)
    assert load_calls["n"] == 1
