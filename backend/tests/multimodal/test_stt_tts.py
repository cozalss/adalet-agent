"""STT + TTS — temel kontrat testleri.

Gerçek faster-whisper / piper-tts opsiyonel dependency'ler — test ortamında
genelde kurulu değil. transcribe/synthesize ImportError'u graceful handle
edip STTResult/TTSResult döner; bunu test ediyoruz.
"""

from __future__ import annotations

import pytest

from multimodal.stt import STTResult, transcribe_audio
from multimodal.tts import TTSResult, _prepare_text, _wav_duration_s, synthesize_speech

# --------------------------------------------------------------------------
#  STT
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transcribe_empty_bytes():
    r = await transcribe_audio(b"")
    assert isinstance(r, STTResult)
    assert r.text == ""
    assert r.error and "boş" in r.error.lower()


@pytest.mark.asyncio
async def test_transcribe_unsupported_ext():
    r = await transcribe_audio(b"abc", ext="xyz")
    assert r.error and "desteklenmeyen" in r.error.lower()


@pytest.mark.asyncio
async def test_transcribe_returns_stt_result_shape():
    """faster-whisper olmasa bile contract korunmalı."""
    r = await transcribe_audio(b"fake-wav-bytes", ext="wav")
    assert isinstance(r, STTResult)
    # Modul yoksa error set olmalı
    if r.error:
        assert "faster-whisper" in r.error.lower() or "stt" in r.error.lower()


# --------------------------------------------------------------------------
#  TTS — _prepare_text helper'ları (model-bağımsız)
# --------------------------------------------------------------------------

def test_prepare_text_strips_disclaimer():
    text = (
        "Kıdem tazminatı işten ayrılma tazminatıdır.\n\n"
        "⚠️ Bu cevap hukuki tavsiye değildir, sadece bilgilendirme amaçlıdır."
    )
    cleaned = _prepare_text(text, strip_disclaimer=True, max_chars=2000)
    assert "Bu cevap hukuki tavsiye" not in cleaned
    assert "Kıdem tazminatı" in cleaned


def test_prepare_text_keeps_disclaimer_when_false():
    text = "Cevap. ⚠️ Bu cevap hukuki tavsiye değildir, danışın."
    cleaned = _prepare_text(text, strip_disclaimer=False, max_chars=2000)
    assert "hukuki tavsiye" in cleaned


def test_prepare_text_truncates_at_sentence_boundary():
    sentences = " ".join(f"Cümle {i}." for i in range(1, 50))
    cleaned = _prepare_text(sentences, strip_disclaimer=False, max_chars=120)
    assert len(cleaned) <= 120
    # Cümle sınırında kesilmiş olmalı (nokta ile biten)
    assert cleaned.endswith(".")


def test_wav_duration_s_basic():
    # 1 saniye 16kHz mono 16-bit = 32000 byte + 44 header
    fake_wav = b"\x00" * (44 + 32000)
    duration = _wav_duration_s(fake_wav, 16000)
    assert duration == 1.0


def test_wav_duration_s_invalid_returns_zero():
    assert _wav_duration_s(b"short", 16000) == 0.0
    assert _wav_duration_s(b"\x00" * 100, 0) == 0.0


# --------------------------------------------------------------------------
#  TTS — synthesize_speech (model yoksa graceful)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_synthesize_empty_text():
    r = await synthesize_speech("")
    assert isinstance(r, TTSResult)
    assert r.audio_bytes == b""
    assert r.error and "boş" in r.error.lower()


@pytest.mark.asyncio
async def test_synthesize_disabled_returns_error(monkeypatch):
    monkeypatch.setattr("multimodal.tts.TTS_ENGINE", "none")
    r = await synthesize_speech("Test")
    assert r.error and "disabled" in r.error.lower()


@pytest.mark.asyncio
async def test_synthesize_returns_tts_result_shape():
    """piper-tts olmasa bile TTSResult contract korunmalı."""
    r = await synthesize_speech("Kıdem tazminatı nedir?")
    assert isinstance(r, TTSResult)
    # Model yoksa error set olur; varsa audio_bytes dolu
    assert r.error is not None or len(r.audio_bytes) > 0
