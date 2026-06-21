"""Bulut STT (OpenAI gpt-4o-transcribe) + routing + lokal fallback testleri.

Gerçek ağ çağrısı YOK — transcribe_openai / httpx.AsyncClient mock'lanır.
conftest autouse fixture'ı OPENAI_API_KEY'i temizler (deterministik).
"""

from __future__ import annotations

import httpx
import pytest

import core.openai_compat as openai_compat
import multimodal.stt as stt
import multimodal.stt_cloud as cloud
from multimodal.stt import transcribe_audio
from multimodal.stt_cloud import cloud_stt_enabled

# --------------------------------------------------------------------------
#  Routing
# --------------------------------------------------------------------------

def test_cloud_enabled_reflects_key(monkeypatch):
    assert cloud_stt_enabled() is False  # conftest temizledi
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert cloud_stt_enabled() is True


def test_use_cloud_provider_local_never(monkeypatch):
    monkeypatch.setattr(stt, "STT_PROVIDER", "local")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert stt._use_cloud() is False  # local: anahtar olsa bile bulut yok


def test_use_cloud_provider_openai_always(monkeypatch):
    monkeypatch.setattr(stt, "STT_PROVIDER", "openai")
    assert stt._use_cloud() is True  # anahtar yoksa bile dener (sonra fallback)


def test_use_cloud_auto_depends_on_key(monkeypatch):
    monkeypatch.setattr(stt, "STT_PROVIDER", "auto")
    assert stt._use_cloud() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert stt._use_cloud() is True


# --------------------------------------------------------------------------
#  transcribe_audio yönlendirme + fallback
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_routes_to_cloud_on_success(monkeypatch):
    monkeypatch.setattr(stt, "STT_PROVIDER", "openai")

    async def fake_cloud(audio_bytes, *, ext, language, timeout_s):
        return "Kıdem tazminatı nedir"

    monkeypatch.setattr(stt, "transcribe_openai", fake_cloud)

    r = await transcribe_audio(b"fake-audio", ext="wav")

    assert r.text == "Kıdem tazminatı nedir"
    assert r.engine == "openai:gpt-4o-transcribe"
    assert r.error is None


@pytest.mark.asyncio
async def test_cloud_failure_falls_back_to_local(monkeypatch):
    monkeypatch.setattr(stt, "STT_PROVIDER", "openai")
    monkeypatch.setattr(stt, "STT_CLOUD_FALLBACK", True)

    async def boom(*_a, **_k):
        raise RuntimeError("ağ hatası")

    monkeypatch.setattr(stt, "transcribe_openai", boom)

    class FakeEngine:
        def transcribe_file(self, path, language="tr", vad_filter=True):
            return "lokal yedek metin", [], 1.0, "tr"

    monkeypatch.setattr(stt, "get_engine", lambda: FakeEngine())

    r = await transcribe_audio(b"fake-audio", ext="wav")

    assert r.text == "lokal yedek metin"            # bulut patladı → lokal'e düştü
    assert r.engine != "openai:gpt-4o-transcribe"
    assert r.error is None


@pytest.mark.asyncio
async def test_cloud_failure_no_fallback_returns_error(monkeypatch):
    monkeypatch.setattr(stt, "STT_PROVIDER", "openai")
    monkeypatch.setattr(stt, "STT_CLOUD_FALLBACK", False)

    async def boom(*_a, **_k):
        raise RuntimeError("ağ hatası")

    monkeypatch.setattr(stt, "transcribe_openai", boom)

    r = await transcribe_audio(b"fake-audio", ext="wav")

    assert r.text == ""
    assert r.error and "bulut" in r.error.lower()


# --------------------------------------------------------------------------
#  transcribe_openai — istek kurulumu (httpx mock)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transcribe_openai_builds_request(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    captured: dict = {}

    class FakeResp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"text": "  merhaba dünya  "}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, data=None, files=None):
            captured.update(url=url, headers=headers, data=data, files=files)
            return FakeResp()

    monkeypatch.setattr(cloud.httpx, "AsyncClient", FakeClient)

    text = await cloud.transcribe_openai(b"audio", ext="wav", language="tr", timeout_s=30)

    assert text == "merhaba dünya"  # strip uygulandı
    assert captured["url"].endswith("/audio/transcriptions")
    assert captured["headers"]["Authorization"] == "Bearer sk-test-123"
    assert captured["data"]["model"] == "gpt-4o-transcribe"
    assert captured["data"]["language"] == "tr"
    assert captured["files"]["file"][2] == "audio/wav"  # doğru MIME


@pytest.mark.asyncio
async def test_transcribe_openai_no_key_raises():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await cloud.transcribe_openai(b"audio", ext="wav", language="tr", timeout_s=30)


@pytest.mark.asyncio
async def test_transcribe_openai_retries_on_503(monkeypatch):
    """Geçici 503 → exponential-backoff retry; ikinci deneme başarılı (lokal'e düşmeden)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def _no_sleep(_s):  # backoff beklemesini test'te atla
        return None

    monkeypatch.setattr(openai_compat.asyncio, "sleep", _no_sleep)
    calls = {"n": 0}

    class Resp503:
        def raise_for_status(self):
            req = httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
            raise httpx.HTTPStatusError("503", request=req, response=httpx.Response(503, request=req))

    class RespOK:
        def raise_for_status(self):
            pass

        def json(self):
            return {"text": "ikinci deneme"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, data=None, files=None):
            calls["n"] += 1
            return Resp503() if calls["n"] == 1 else RespOK()

    monkeypatch.setattr(cloud.httpx, "AsyncClient", lambda *_a, **_k: FakeClient())

    text = await cloud.transcribe_openai(b"audio", ext="wav", language="tr", timeout_s=30)

    assert text == "ikinci deneme"
    assert calls["n"] == 2  # 1 başarısız + 1 retry başarılı


@pytest.mark.asyncio
async def test_transcribe_openai_rejects_oversized_audio(monkeypatch):
    """Ön-yükleme boyut kıskacı: büyük blob OpenAI'ye gitmeden reddedilir (bant-genişliği/maliyet)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(cloud, "_MAX_AUDIO_BYTES", 10)
    with pytest.raises(ValueError, match="çok büyük"):
        await cloud.transcribe_openai(b"x" * 20, ext="wav", language="tr", timeout_s=30)
