"""Multimodal endpoint'ler — OCR / STT / TTS.

  POST /multimodal/ocr   — multipart: image=<file>           → text
  POST /multimodal/stt   — multipart: audio=<file>           → text
  POST /multimodal/tts   — JSON: {text: ...}                 → audio/wav bytes

Boyut sınırı: OCR 20MB, STT 25MB, TTS 8KB metin. Üst sınırı geçen request
413 döner. MIME tipleri whitelist'li.

KVKK: yüklenen dosyalar inference sonrası tutulmaz; geçici dosya finally
bloğunda silinir.
"""

from __future__ import annotations

import re
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.middleware.auth import Principal, authenticate
from api.schemas import OCRUploadResponse, STTUploadResponse
from multimodal.ocr import extract_text
from multimodal.stt import transcribe_audio
from multimodal.tts import synthesize_speech

log = structlog.get_logger()
router = APIRouter(prefix="/multimodal", tags=["multimodal"])

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_TTS_CHARS = 8000

_ALLOWED_IMAGE_MIMES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/tiff",
    "application/pdf",  # tek-sayfa PDF tarama
}
_ALLOWED_AUDIO_MIMES = {
    "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3",
    "audio/mp4", "audio/m4a", "audio/x-m4a",
    "audio/ogg", "audio/webm", "audio/flac",
}
_ALLOWED_AUDIO_EXTS = {"wav", "mp3", "m4a", "ogg", "webm", "flac", "mp4"}

# Sprint-4 W7.5: filename sanitize — path traversal + null byte
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_filename(name: str | None, default: str = "upload") -> str:
    """Filename'den path bileşeni, null byte, control char temizle.

    `../../../etc/passwd` → `etcpasswd`; `\\x00..rm.png` → `rm.png`.
    Yalnız base + extension karakterleri kalır.
    """
    if not name:
        return default
    base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    cleaned = _SAFE_FILENAME_RE.sub("_", base).strip("._")
    return cleaned[:128] or default


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TTS_CHARS)
    strip_disclaimer: bool = True


# --------------------------------------------------------------------------
#  OCR
# --------------------------------------------------------------------------

@router.post("/ocr", response_model=OCRUploadResponse)
async def ocr_upload(
    image: Annotated[UploadFile, File(...)],
    principal: Principal = Depends(authenticate),
) -> OCRUploadResponse:
    """Belge fotoğrafı → metin (Tesseract TR; auto-fallback Qwen-VL)."""
    _ = principal
    safe_name = _sanitize_filename(image.filename, "image")
    if image.content_type and image.content_type not in _ALLOWED_IMAGE_MIMES:
        raise HTTPException(415, f"Desteklenmeyen tip: {image.content_type}")
    data = await image.read()
    if not data:
        raise HTTPException(400, "Boş dosya")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            413, f"Görüntü > {MAX_IMAGE_BYTES // (1024 * 1024)} MB",
        )

    result = await extract_text(data, engine="auto")
    log.info(
        "ocr_request",
        filename=safe_name, mime=image.content_type,
        engine=result.engine, n_chars=result.n_chars,
    )
    return OCRUploadResponse(
        text=result.text,
        engine=result.engine,
        n_chars=result.n_chars,
        elapsed_ms=result.elapsed_ms,
        error=result.error,
    )


# --------------------------------------------------------------------------
#  STT
# --------------------------------------------------------------------------

@router.post("/stt", response_model=STTUploadResponse)
async def stt_upload(
    audio: Annotated[UploadFile, File(...)],
    principal: Principal = Depends(authenticate),
) -> STTUploadResponse:
    """Ses dosyası → Türkçe metin (faster-whisper)."""
    _ = principal
    safe_name = _sanitize_filename(audio.filename, "audio")
    if audio.content_type and audio.content_type not in _ALLOWED_AUDIO_MIMES:
        raise HTTPException(415, f"Desteklenmeyen tip: {audio.content_type}")
    data = await audio.read()
    if not data:
        raise HTTPException(400, "Boş dosya")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(
            413, f"Ses > {MAX_AUDIO_BYTES // (1024 * 1024)} MB",
        )

    # Sanitize edilmiş filename'den ext çıkar — whitelist
    ext = "wav"
    if "." in safe_name:
        candidate = safe_name.rsplit(".", 1)[-1].lower()
        if candidate in _ALLOWED_AUDIO_EXTS:
            ext = candidate

    result = await transcribe_audio(data, ext=ext)
    log.info(
        "stt_request",
        filename=safe_name, ext=ext,
        n_chars=len(result.text), duration=result.duration_s,
    )
    return STTUploadResponse(
        text=result.text,
        language=result.language,
        duration_s=result.duration_s,
        elapsed_ms=result.elapsed_ms,
        error=result.error,
    )


# --------------------------------------------------------------------------
#  TTS
# --------------------------------------------------------------------------

@router.post("/tts")
async def tts_generate(
    req: TTSRequest,
    principal: Principal = Depends(authenticate),
) -> Response:
    _ = principal
    """Metin → 16kHz WAV bytes. Content-Type: audio/wav."""
    result = await synthesize_speech(req.text, strip_disclaimer=req.strip_disclaimer)
    if result.error and not result.audio_bytes:
        raise HTTPException(503, f"TTS hata: {result.error}")

    headers = {
        "X-TTS-Engine": result.engine,
        "X-TTS-Duration-S": str(result.duration_s),
        "X-TTS-Elapsed-MS": str(result.elapsed_ms),
    }
    return Response(content=result.audio_bytes, media_type="audio/wav", headers=headers)
