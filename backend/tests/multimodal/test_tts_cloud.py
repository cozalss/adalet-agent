"""Bulut TTS (OpenAI) + routing + Piper fallback. Gerçek ağ YOK (httpx mock).

conftest autouse OPENAI_API_KEY'i temizler (deterministik).
"""

from __future__ import annotations

import struct

import pytest

import multimodal.tts as tts
import multimodal.tts_cloud as tts_cloud
from multimodal.tts import _use_cloud_tts, _wav_sample_rate, synthesize_speech


def _wav(sample_rate: int = 24000, n_samples: int = 2400) -> bytes:
    data = b"\x00\x00" * n_samples
    return (
        b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data" + struct.pack("<I", len(data)) + data
    )


def test_wav_sample_rate():
    assert _wav_sample_rate(_wav(24000)) == 24000
    assert _wav_sample_rate(_wav(16000)) == 16000
    assert _wav_sample_rate(b"not a wav") == 24000  # default


def test_use_cloud_tts_routing(monkeypatch):
    monkeypatch.setattr(tts, "TTS_PROVIDER", "local")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert _use_cloud_tts() is False
    monkeypatch.setattr(tts, "TTS_PROVIDER", "openai")
    assert _use_cloud_tts() is True
    monkeypatch.setattr(tts, "TTS_PROVIDER", "auto")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _use_cloud_tts() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert _use_cloud_tts() is True


@pytest.mark.asyncio
async def test_synthesize_routes_to_cloud(monkeypatch):
    monkeypatch.setattr(tts, "TTS_PROVIDER", "openai")
    monkeypatch.setattr(tts, "TTS_ENGINE", "piper")  # "none" değil

    async def fake_cloud(text, *, timeout_s, model=None, voice=None):
        return _wav(24000)

    monkeypatch.setattr(tts, "synthesize_openai", fake_cloud)

    r = await synthesize_speech("Kıdem tazminatı nedir?")
    assert r.engine == "openai-tts"
    assert r.sample_rate == 24000
    assert len(r.audio_bytes) > 44
    assert r.error is None


@pytest.mark.asyncio
async def test_cloud_failure_falls_back_to_piper(monkeypatch):
    monkeypatch.setattr(tts, "TTS_PROVIDER", "openai")
    monkeypatch.setattr(tts, "TTS_CLOUD_FALLBACK", True)
    monkeypatch.setattr(tts, "TTS_ENGINE", "piper")

    async def boom(*_a, **_k):
        raise RuntimeError("ağ hatası")

    monkeypatch.setattr(tts, "synthesize_openai", boom)

    class FakeEngine:
        def synthesize_wav(self, text):
            return _wav(22050), 22050

    monkeypatch.setattr(tts, "get_engine", lambda: FakeEngine())

    r = await synthesize_speech("Merhaba")
    assert r.engine != "openai-tts"   # bulut patladı → Piper'a düştü
    assert r.error is None
    assert r.sample_rate == 22050


@pytest.mark.asyncio
async def test_cloud_failure_no_fallback_returns_error(monkeypatch):
    monkeypatch.setattr(tts, "TTS_PROVIDER", "openai")
    monkeypatch.setattr(tts, "TTS_CLOUD_FALLBACK", False)

    async def boom(*_a, **_k):
        raise RuntimeError("ağ hatası")

    monkeypatch.setattr(tts, "synthesize_openai", boom)

    r = await synthesize_speech("Merhaba")
    assert r.engine == "openai-tts"
    assert r.error and "bulut" in r.error.lower()


@pytest.mark.asyncio
async def test_synthesize_openai_builds_request(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-tts")
    captured: dict = {}

    class FakeResp:
        content = _wav(24000)

        def raise_for_status(self) -> None:
            pass

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            captured.update(url=url, headers=headers, payload=json)
            return FakeResp()

    monkeypatch.setattr(tts_cloud.httpx, "AsyncClient", FakeClient)

    audio = await tts_cloud.synthesize_openai("Merhaba dünya", timeout_s=30)

    assert audio[:4] == b"RIFF"
    assert captured["url"].endswith("/audio/speech")
    assert captured["headers"]["Authorization"] == "Bearer sk-test-tts"
    assert captured["payload"]["response_format"] == "wav"
    assert captured["payload"]["input"] == "Merhaba dünya"


@pytest.mark.asyncio
async def test_synthesize_openai_no_key_raises():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await tts_cloud.synthesize_openai("x", timeout_s=30)
