"""TTS — Türkçe metni sesli cevaba çevir.

Engine: **Piper** (onnxruntime backend, hızlı, küçük, lokal, ücretsiz).
  - Türkçe modeli: `tr_TR-fettah-medium` (Rhasspy/piper-voices HF)
  - Boyut: ~60 MB (.onnx + .json), CPU'da real-time 8x
  - INT8 onnx model — Pi 4'te bile çalışır

Alternatif: **Coqui XTTS-v2** — daha doğal ama 1.5 GB, GPU önerilir.
Default: Piper (production lokal CPU, mobil entegre).

Akış:
  1. Lazy load Piper voice (~60MB onnx)
  2. synthesize(text) → 16kHz WAV bytes
  3. Caller: SSE stream, mobil push, file download

Sınır:
  - Tek seferlik max 2000 char (TTS uzun cevaplarda anlamsız)
  - Disclaimer otomatik kesilir (her cevapta tekrarlanması yorucu)

ENV:
    TTS_ENGINE=piper|coqui|none           (default piper; "none" → kapalı)
    TTS_MODEL=tr_TR-fettah-medium
    TTS_VOICE_DIR=~/.cache/piper          (model cache)
    TTS_MAX_CHARS=2000
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import structlog

log = structlog.get_logger()

TTS_ENGINE = os.getenv("TTS_ENGINE", "piper").lower()
# 2026-05-26: rhasspy/piper-voices TR repo'sunda mevcut tek voice DFKI
# (eskiden fettah ismiyle planlanmıştı, gerçek upload DFKI). ENV ile override:
TTS_MODEL = os.getenv("TTS_MODEL", "tr_TR-dfki-medium")
# Sprint-6: backend/models/piper/ altındaki HF mirror path varsayılan
_DEFAULT_VOICE_DIR = Path(__file__).parent.parent / "models" / "piper" / "tr" / "tr_TR" / "dfki" / "medium"
TTS_VOICE_DIR = Path(
    os.getenv("TTS_VOICE_DIR", str(_DEFAULT_VOICE_DIR)),
)
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "2000"))
TTS_TIMEOUT_S = float(os.getenv("TTS_TIMEOUT_S", "30"))

# Hukuki disclaimer'ı TTS'e gönderirken kes — her cevapta tekrarlanması kötü UX
_DISCLAIMER_MARKERS = (
    "Bu cevap hukuki tavsiye değildir",
    "⚠️",
    "---\n**Kaynaklar",
)


@dataclass(slots=True)
class TTSResult:
    audio_bytes: bytes
    sample_rate: int
    duration_s: float
    elapsed_ms: int
    engine: str = TTS_ENGINE
    n_chars: int = 0
    error: str | None = None


# --------------------------------------------------------------------------
#  Piper engine
# --------------------------------------------------------------------------

class PiperEngine:
    """Piper voice singleton — lazy onnx load."""

    def __init__(self, voice_name: str = TTS_MODEL, voice_dir: Path = TTS_VOICE_DIR) -> None:
        self.voice_name = voice_name
        self.voice_dir = voice_dir

    @cached_property
    def _voice(self):
        from piper import PiperVoice

        # piper-tts paketinde voice dosya konvansiyonu: <name>.onnx + .onnx.json
        onnx_path = self.voice_dir / f"{self.voice_name}.onnx"
        if not onnx_path.exists():
            raise FileNotFoundError(
                f"Piper voice bulunamadı: {onnx_path}. "
                f"İndir: https://huggingface.co/rhasspy/piper-voices/tree/main/tr/tr_TR"
            )
        log.info("tts_loading_piper", voice=str(onnx_path))
        return PiperVoice.load(str(onnx_path))

    def synthesize_wav(self, text: str) -> tuple[bytes, int]:
        """Tek pass synthesize → (wav_bytes, sample_rate).

        piper-tts v1.4+: ``synthesize_wav(text, wav_file, set_wav_format=True)``
        otomatik header (channels, sample_rate, sample_width) yazar. Eskiden
        düz ``synthesize(text, wav)`` çalışıyordu, kaldırıldı.
        """
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            self._voice.synthesize_wav(text, wav, set_wav_format=True)
        sample_rate = self._voice.config.sample_rate
        return buf.getvalue(), sample_rate


_engine_singleton: PiperEngine | None = None


def get_engine() -> PiperEngine:
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = PiperEngine()
    return _engine_singleton


def reset_engine() -> None:
    global _engine_singleton
    _engine_singleton = None


# --------------------------------------------------------------------------
#  Public API
# --------------------------------------------------------------------------

async def synthesize_speech(
    text: str,
    *,
    strip_disclaimer: bool = True,
    max_chars: int = TTS_MAX_CHARS,
) -> TTSResult:
    """Metin → 16kHz WAV bytes.

    Args:
        text: cevap metni
        strip_disclaimer: True → "Bu cevap hukuki tavsiye değildir..." kısmı
                          ve sonrası kesilir
        max_chars: aşılırsa cümle sınırında kes
    """
    if TTS_ENGINE == "none":
        return TTSResult(
            audio_bytes=b"", sample_rate=0, duration_s=0.0,
            elapsed_ms=0, engine="none", n_chars=0,
            error="TTS disabled (TTS_ENGINE=none)",
        )
    if not text or not text.strip():
        return TTSResult(
            audio_bytes=b"", sample_rate=0, duration_s=0.0,
            elapsed_ms=0, n_chars=0, error="boş metin",
        )

    cleaned = _prepare_text(text, strip_disclaimer=strip_disclaimer, max_chars=max_chars)
    start = time.perf_counter()

    try:
        engine = get_engine()
        try:
            audio, sample_rate = await asyncio.wait_for(
                asyncio.to_thread(engine.synthesize_wav, cleaned),
                timeout=TTS_TIMEOUT_S,
            )
        except TimeoutError:
            return TTSResult(
                audio_bytes=b"", sample_rate=0, duration_s=0.0,
                elapsed_ms=int(TTS_TIMEOUT_S * 1000),
                n_chars=len(cleaned), error="tts timeout",
            )
    except ImportError as exc:
        return TTSResult(
            audio_bytes=b"", sample_rate=0, duration_s=0.0,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            n_chars=len(cleaned), error=f"piper-tts yok: {exc}",
        )
    except FileNotFoundError as exc:
        return TTSResult(
            audio_bytes=b"", sample_rate=0, duration_s=0.0,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            n_chars=len(cleaned), error=str(exc),
        )
    except Exception as exc:
        log.exception("tts_failed", error=str(exc))
        return TTSResult(
            audio_bytes=b"", sample_rate=0, duration_s=0.0,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            n_chars=len(cleaned), error=f"tts hata: {exc!s}",
        )

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    duration_s = _wav_duration_s(audio, sample_rate)
    log.info(
        "tts_done", n_chars=len(cleaned), duration_s=duration_s,
        sample_rate=sample_rate, elapsed_ms=elapsed_ms,
    )
    return TTSResult(
        audio_bytes=audio,
        sample_rate=sample_rate,
        duration_s=duration_s,
        elapsed_ms=elapsed_ms,
        n_chars=len(cleaned),
    )


# --------------------------------------------------------------------------
#  Helpers
# --------------------------------------------------------------------------

def _prepare_text(
    text: str,
    *,
    strip_disclaimer: bool,
    max_chars: int,
) -> str:
    """Disclaimer'ı kes + char limiti uygula (cümle sınırında)."""
    cleaned = text.strip()
    if strip_disclaimer:
        for marker in _DISCLAIMER_MARKERS:
            idx = cleaned.find(marker)
            if idx > 0:
                cleaned = cleaned[:idx].rstrip()
                break

    if len(cleaned) <= max_chars:
        return cleaned

    # Cümle sınırında kes — son . ! ? işaretine kadar
    truncated = cleaned[:max_chars]
    last_period = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
    if last_period > max_chars * 0.6:
        truncated = truncated[: last_period + 1]
    return truncated.strip()


def _wav_duration_s(audio_bytes: bytes, sample_rate: int) -> float:
    """WAV bytes'tan duration tahmini — header 44 byte + 16-bit mono."""
    if sample_rate <= 0 or len(audio_bytes) < 44:
        return 0.0
    n_samples = (len(audio_bytes) - 44) / 2  # 16-bit = 2 byte
    return round(n_samples / sample_rate, 2)


__all__ = ("PiperEngine", "TTSResult", "get_engine", "reset_engine", "synthesize_speech")
