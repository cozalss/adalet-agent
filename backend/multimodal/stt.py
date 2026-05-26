"""STT — sesli kullanıcı girdisini Türkçe metne çevir.

Engine: **faster-whisper** (CTranslate2 backend, Whisper-large-v3 TR).
  - Whisper'ın 2-4x hızlı versiyonu, INT8 CPU veya FP16 GPU.
  - Lokal: VAD destekli, kelime-zaman damgaları opsiyonel.
  - Model boyutları: tiny(75MB), base(140MB), small(480MB), medium(1.5GB),
    large-v3(3GB). RTX 4070 12GB'da large-v3 paralel kullanım sığar; CPU'da
    small önerilir.

Akış:
  1. Bytes → temp file (whisper file path bekler) veya numpy decode
  2. Lazy load model (singleton)
  3. transcribe(audio_path, language="tr", vad_filter=True)
  4. Concatenate segments → metin

Fallback: faster-whisper yüklenemezse openai-whisper'a düş; o da yoksa
`STTResult(error=...)` döner ki API graceful 503/422 verebilsin.

Kullanım:
    result = await transcribe_audio(audio_bytes, ext="wav")
    result.text          → "Kıdem tazminatı nedir?"
    result.language      → "tr"
    result.elapsed_ms

ENV:
    STT_ENGINE=faster-whisper|whisper       (default faster-whisper)
    STT_MODEL=large-v3|medium|small|base    (default small — CPU dostu)
    STT_DEVICE=cpu|cuda                     (default cpu — model swap)
    STT_COMPUTE_TYPE=int8|float16|float32   (default int8 CPU, float16 cuda)
    STT_LANG=tr
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import time
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import structlog

log = structlog.get_logger()

STT_ENGINE = os.getenv("STT_ENGINE", "faster-whisper").lower()
# Sprint-6: local path varsayılan, faster-whisper'ın local model dizinini kabul eder.
# HF download'la backend/models/whisper/ altında Systran/faster-whisper-small mevcut.
_DEFAULT_WHISPER_DIR = Path(__file__).parent.parent / "models" / "whisper"
STT_MODEL = os.getenv(
    "STT_MODEL",
    str(_DEFAULT_WHISPER_DIR) if _DEFAULT_WHISPER_DIR.exists() else "small",
)
STT_DEVICE = os.getenv("STT_DEVICE", "cpu")
STT_COMPUTE_TYPE = os.getenv(
    "STT_COMPUTE_TYPE",
    "float16" if STT_DEVICE == "cuda" else "int8",
)
STT_LANG = os.getenv("STT_LANG", "tr")
STT_TIMEOUT_S = float(os.getenv("STT_TIMEOUT_S", "120"))

_ALLOWED_EXTS = {"wav", "mp3", "m4a", "ogg", "flac", "webm"}


@dataclass(slots=True)
class STTSegment:
    """Whisper segment — başlangıç/bitiş + metin (kelime damgası opsiyonel)."""

    start_s: float
    end_s: float
    text: str


@dataclass(slots=True)
class STTResult:
    text: str
    language: str
    duration_s: float
    elapsed_ms: int
    segments: list[STTSegment] = field(default_factory=list)
    engine: str = STT_ENGINE
    error: str | None = None


# --------------------------------------------------------------------------
#  Engine wrapper
# --------------------------------------------------------------------------

class STTEngine:
    """faster-whisper lazy-loaded singleton."""

    def __init__(
        self,
        model_name: str = STT_MODEL,
        device: str = STT_DEVICE,
        compute_type: str = STT_COMPUTE_TYPE,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type

    @cached_property
    def _model(self):
        from faster_whisper import WhisperModel

        log.info(
            "stt_loading",
            model=self.model_name, device=self.device, compute=self.compute_type,
        )
        return WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
        )

    def transcribe_file(
        self,
        audio_path: str,
        language: str = STT_LANG,
        vad_filter: bool = True,
    ) -> tuple[str, list[STTSegment], float, str]:
        """Tek dosya transcribe → (text, segments, duration_s, detected_lang)."""
        segments_iter, info = self._model.transcribe(
            audio_path,
            language=language,
            vad_filter=vad_filter,
            beam_size=5,
            condition_on_previous_text=False,  # halüsinasyon önle
        )
        segments: list[STTSegment] = []
        text_parts: list[str] = []
        for seg in segments_iter:
            segments.append(STTSegment(start_s=seg.start, end_s=seg.end, text=seg.text))
            text_parts.append(seg.text)
        text = " ".join(t.strip() for t in text_parts).strip()
        return text, segments, float(info.duration), info.language


# --------------------------------------------------------------------------
#  Public API
# --------------------------------------------------------------------------

_engine_singleton: STTEngine | None = None


def get_engine() -> STTEngine:
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = STTEngine()
    return _engine_singleton


def reset_engine() -> None:
    global _engine_singleton
    _engine_singleton = None


async def transcribe_audio(
    audio_bytes: bytes,
    *,
    ext: str = "wav",
    language: str = STT_LANG,
) -> STTResult:
    """Ses bytes'ından Türkçe metne dönüş.

    Args:
        audio_bytes: ham ses dosyası bytes
        ext: dosya uzantısı (whitelisted: wav/mp3/m4a/ogg/flac/webm)
        language: ISO 639-1 dil kodu (default "tr")
    """
    if not audio_bytes:
        return STTResult(
            text="", language=language, duration_s=0.0, elapsed_ms=0,
            error="boş ses",
        )

    ext_clean = ext.lower().lstrip(".")
    if ext_clean not in _ALLOWED_EXTS:
        return STTResult(
            text="", language=language, duration_s=0.0, elapsed_ms=0,
            error=f"desteklenmeyen format: {ext_clean}",
        )

    start = time.perf_counter()
    tmp_path: Path | None = None
    try:
        # Whisper file-path bekler — temp file
        with tempfile.NamedTemporaryFile(
            suffix=f".{ext_clean}", delete=False,
        ) as f:
            f.write(audio_bytes)
            tmp_path = Path(f.name)

        engine = get_engine()
        try:
            text, segments, duration, detected_lang = await asyncio.wait_for(
                asyncio.to_thread(engine.transcribe_file, str(tmp_path), language),
                timeout=STT_TIMEOUT_S,
            )
        except TimeoutError:
            return STTResult(
                text="", language=language, duration_s=0.0,
                elapsed_ms=int(STT_TIMEOUT_S * 1000),
                error=f"stt timeout ({STT_TIMEOUT_S}s)",
            )
        except ImportError as exc:
            return STTResult(
                text="", language=language, duration_s=0.0,
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                error=f"faster-whisper yok: {exc}",
            )
        except Exception as exc:
            log.exception("stt_failed", error=str(exc))
            return STTResult(
                text="", language=language, duration_s=0.0,
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                error=f"stt hata: {exc!s}",
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        log.info(
            "stt_done", duration_s=duration, n_chars=len(text),
            lang=detected_lang, elapsed_ms=elapsed_ms,
        )
        return STTResult(
            text=text,
            language=detected_lang,
            duration_s=duration,
            elapsed_ms=elapsed_ms,
            segments=segments,
        )
    finally:
        if tmp_path and tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()


__all__ = ("STTEngine", "STTResult", "STTSegment", "get_engine", "reset_engine", "transcribe_audio")
