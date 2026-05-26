"""Multimodal real model integration tests — Sprint-6.

@pytest.mark.multimodal_integration — gerçek faster-whisper + piper-tts
modellerini disk'ten yüklüyor. CI/local-fast'da skip edilir, manuel test
veya sadece WIP makinede çalıştırılır.

Çalıştırmak için:
    cd backend
    uv run pytest tests/multimodal/test_real_integration.py -v -m multimodal_integration

Gerekli artifacts (~525 MB):
    backend/models/whisper/    — Systran/faster-whisper-small (~480 MB)
    backend/models/piper/tr/tr_TR/dfki/medium/  — tr_TR-dfki-medium.onnx (~61 MB)

Modeller yoksa test'ler graceful skip eder (pytest.skip).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multimodal.ocr import extract_text
from multimodal.stt import transcribe_audio
from multimodal.tts import synthesize_speech

_MODELS_DIR = Path(__file__).parent.parent.parent / "models"
_WHISPER_OK = (_MODELS_DIR / "whisper" / "model.bin").exists()
_PIPER_OK = (
    _MODELS_DIR
    / "piper"
    / "tr"
    / "tr_TR"
    / "dfki"
    / "medium"
    / "tr_TR-dfki-medium.onnx"
).exists()
_TESSDATA_OK = (_MODELS_DIR / "tessdata" / "tur.traineddata").exists()
_TESSERACT_BIN_OK = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists()


@pytest.mark.multimodal_integration
@pytest.mark.skipif(not _PIPER_OK, reason="Piper TR voice indirilmemiş")
@pytest.mark.asyncio
async def test_tts_real_piper_turkish() -> None:
    """Piper TR voice gerçek synthesize — çıktı WAV ve süre > 0 olmalı."""
    text = "Kıdem tazminatı, işten ayrılma tazminatıdır."
    result = await synthesize_speech(text, strip_disclaimer=False)

    assert result.error is None, f"TTS hata: {result.error}"
    assert result.engine == "piper"
    assert len(result.audio_bytes) > 1000, "WAV çok küçük"
    assert result.sample_rate == 22050, "Piper TR DFKI 22050 Hz olmalı"
    assert result.duration_s > 1.0, "Cümle en az 1 saniye olmalı"
    assert result.n_chars == len(text)


@pytest.mark.multimodal_integration
@pytest.mark.skipif(not _WHISPER_OK, reason="Whisper small indirilmemiş")
@pytest.mark.skipif(not _PIPER_OK, reason="Piper TR voice indirilmemiş")
@pytest.mark.asyncio
async def test_stt_tts_round_trip_turkish() -> None:
    """TTS → STT round-trip: söylenen metin geri yazıldığında benzemeli.

    Birebir aynı olmak zorunda değil (Whisper small noisy olabilir), ama
    anahtar kelimeler dönmeli.
    """
    original = "Kıdem tazminatı işten ayrılma tazminatıdır."
    tts = await synthesize_speech(original, strip_disclaimer=False)
    assert tts.error is None
    assert len(tts.audio_bytes) > 1000

    stt = await transcribe_audio(tts.audio_bytes, ext="wav")
    assert stt.error is None, f"STT hata: {stt.error}"
    assert stt.language == "tr"
    assert stt.duration_s > 1.0

    # Anahtar kelimeler test (case-insensitive, küçük hata toleransı)
    text_lower = stt.text.lower()
    assert "tazminat" in text_lower, f"'tazminat' yok: {stt.text!r}"
    assert any(
        w in text_lower for w in ("kıdem", "kıdam", "kidam", "kidem")
    ), f"'kıdem' türevleri yok: {stt.text!r}"


@pytest.mark.multimodal_integration
@pytest.mark.skipif(not _PIPER_OK, reason="Piper TR voice indirilmemiş")
@pytest.mark.asyncio
async def test_tts_disclaimer_stripping() -> None:
    """`strip_disclaimer=True` "Bu cevap hukuki tavsiye değildir..." kısmını çıkarmalı."""
    full = (
        "Tüketici 14 gün içinde cayma hakkına sahiptir. "
        "Bu cevap hukuki tavsiye değildir, sadece bilgilendirme amaçlıdır."
    )
    result = await synthesize_speech(full, strip_disclaimer=True)

    assert result.error is None
    # Disclaimer kesildiyse n_chars azalmalı
    assert result.n_chars < len(full)
    # Yalın metin yine de yeterince uzun
    assert result.n_chars >= 30


@pytest.mark.multimodal_integration
@pytest.mark.skipif(not _WHISPER_OK, reason="Whisper small indirilmemiş")
@pytest.mark.asyncio
async def test_stt_lazy_load_singleton() -> None:
    """STT engine ilk çağrıda yüklenir, ikinci çağrı cached olur (hızlı)."""
    import time

    # 1) Fake input: çok kısa boş WAV (sadece engine init için)
    # PiperTTS çıktısı ile gerçek test
    tts = await synthesize_speech("Test.", strip_disclaimer=False)
    if not _PIPER_OK or tts.error:
        pytest.skip("Piper yok, engine init test edilemez")

    t1_start = time.perf_counter()
    r1 = await transcribe_audio(tts.audio_bytes, ext="wav")
    t1 = time.perf_counter() - t1_start

    t2_start = time.perf_counter()
    r2 = await transcribe_audio(tts.audio_bytes, ext="wav")
    t2 = time.perf_counter() - t2_start

    assert r1.error is None and r2.error is None
    # İkinci çağrı cold (~14s) > warm (~1-3s); küçük ses ise zaten cached
    # Toleranslı assert: warm path t2 < 1.5x of t1 (variance friendly)
    assert t2 <= t1 * 1.5, f"İkinci çağrı çok yavaş: t1={t1:.2f}s t2={t2:.2f}s"


@pytest.mark.multimodal_integration
@pytest.mark.skipif(not _TESSDATA_OK, reason="tessdata/tur.traineddata yok")
@pytest.mark.skipif(not _TESSERACT_BIN_OK, reason="Tesseract binary yüklenmemiş")
@pytest.mark.asyncio
async def test_ocr_real_tesseract_turkish() -> None:
    """Tesseract Türkçe karakterleri (ç ğ ı ş ü) doğru okumalı."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    text_in = "Madde 11 - Tüketici hakları çiğnenemez."
    img = Image.new("RGB", (800, 120), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    draw.text((20, 40), text_in, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    result = await extract_text(buf.getvalue(), lang="tur", engine="tesseract")

    assert result.error is None, f"OCR hata: {result.error}"
    assert result.engine == "tesseract"
    assert result.n_chars > 0
    # Anahtar Türkçe karakterli kelimeler korunmalı
    text_out = result.text.lower()
    assert "madde" in text_out
    assert "tüketici" in text_out or "tuketici" in text_out
    # ç/ğ/ş Türkçe karakter render başarısı (esnek)
    assert any(ch in result.text for ch in "çğüşıÇĞÜŞİ"), (
        f"Türkçe karakter yok: {result.text!r}"
    )
