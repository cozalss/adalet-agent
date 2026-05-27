"""Iter 12 — multimodal hata string'leri info-disclosure sızdırmamalı.

OCR/STT/TTS runtime exception'ları kullanıcıya dönen `error` alanında ham
exc / dosya yolu / lib adı sızdırmamalı (KVKK + güvenlik). Tam detay sadece
sunucu log'una gider. Meşru kullanıcı mesajları (boş/desteklenmeyen/disabled)
korunur.
"""

from __future__ import annotations

import pytest

from multimodal.stt import transcribe_audio
from multimodal.tts import synthesize_speech

_SECRET = "C:/gizli/model/path-42.bin satır 7"


class _BoomSTTEngine:
    def transcribe_file(self, *_a, **_k):
        raise RuntimeError(_SECRET)


class _BoomPiperEngine:
    def synthesize_wav(self, _text):
        raise RuntimeError(_SECRET)


@pytest.mark.asyncio
async def test_stt_runtime_error_does_not_leak_exc(monkeypatch):
    import multimodal.stt as stt_mod

    monkeypatch.setattr(stt_mod, "get_engine", lambda: _BoomSTTEngine())
    r = await transcribe_audio(b"fake-wav-bytes", ext="wav")

    assert r.error is not None
    assert _SECRET not in r.error
    assert "gizli" not in r.error and ".bin" not in r.error
    # Generic ama anlamlı — "stt" izi (kontrat + test_stt_tts.py:40 uyumu).
    assert "stt" in r.error.lower()


@pytest.mark.asyncio
async def test_tts_runtime_error_does_not_leak_exc(monkeypatch):
    import multimodal.tts as tts_mod

    monkeypatch.setattr(tts_mod, "get_engine", lambda: _BoomPiperEngine())
    r = await synthesize_speech("Kıdem tazminatı nedir?", strip_disclaimer=True)

    assert r.error is not None
    assert _SECRET not in r.error
    assert "gizli" not in r.error and ".bin" not in r.error
    assert "tts" in r.error.lower()


@pytest.mark.asyncio
async def test_tts_file_not_found_does_not_leak_path(monkeypatch):
    """Eksik model/binary FileNotFoundError → dosya YOLU sızmamalı."""
    import multimodal.tts as tts_mod

    def _missing():
        raise FileNotFoundError(_SECRET)

    monkeypatch.setattr(tts_mod, "get_engine", _missing)
    r = await synthesize_speech("merhaba", strip_disclaimer=False)

    assert r.error is not None
    assert _SECRET not in r.error
    assert "gizli" not in r.error and ".bin" not in r.error


@pytest.mark.asyncio
async def test_stt_legit_messages_preserved():
    """Meşru kullanıcı mesajları (boş/desteklenmeyen) sansürlenmemeli."""
    r_empty = await transcribe_audio(b"", ext="wav")
    assert r_empty.error and "boş" in r_empty.error.lower()

    r_bad = await transcribe_audio(b"abc", ext="xyz")
    assert r_bad.error and "desteklenmeyen" in r_bad.error.lower()
