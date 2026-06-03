"""Multimodal endpoint'ler — OCR / STT / TTS.

  POST /multimodal/ocr   — multipart: image=<file>           → text
  POST /multimodal/stt   — multipart: audio=<file>           → text
  POST /multimodal/tts   — JSON: {text: ...}                 → audio/wav bytes

Boyut sınırı: OCR 20MB, STT 25MB, TTS 8KB metin. Üst sınırı geçen request
413 döner. MIME tipleri whitelist'li.

Gizlilik: yüklenen dosyalar inference sonrası tutulmaz; geçici dosya finally
bloğunda silinir.
"""

from __future__ import annotations

import re
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.limiter import limiter
from api.middleware.auth import Principal, authenticate
from api.pii import mask_pii
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
    # Null-byte explicit strip (regex'ten önce; defensive — path-traversal vektörü)
    base = name.replace("\x00", "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    cleaned = _SAFE_FILENAME_RE.sub("_", base).strip("._")
    return cleaned[:128] or default


# Magic-byte imzaları — istemci Content-Type header'ı sahte olabilir; gerçek
# dosya içeriğini ilk byte'lardan doğrula (H1: client-controlled MIME bypass).
def _detect_image_kind(data: bytes) -> str | None:
    """İlk byte'lardan görüntü/PDF türünü tespit et. Tanınmazsa None."""
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[:5] == b"%PDF-":
        return "pdf"
    return None


def _detect_audio_kind(data: bytes) -> str | None:
    """İlk byte'lardan ses türünü tespit et. Tanınmazsa None.

    OCR'daki magic-byte doğrulamasının ses karşılığı (input-validation tutarlılığı):
    istemci `Content-Type: audio/wav` deyip executable/polyglot yollayabilir;
    Whisper'a (ffmpeg/libsndfile) geçmeden önce gerçek içeriği doğrula.
    """
    if len(data) < 12:
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    if data[4:8] == b"ftyp":          # MP4/M4A container (ftyp box)
        return "mp4"
    if data[:3] == b"ID3":            # MP3 (ID3v2 tag)
        return "mp3"
    if data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:  # MP3 frame sync
        return "mp3"
    return None


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TTS_CHARS)
    strip_disclaimer: bool = True


# --------------------------------------------------------------------------
#  OCR
# --------------------------------------------------------------------------

@router.post("/ocr", response_model=OCRUploadResponse)
@limiter.limit("5/minute")  # güvenlik: pahalı OCR (Tesseract+Qwen-VL) DoS guard
async def ocr_upload(
    request: Request,
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
    # H1: gerçek dosya türünü magic-byte'lardan doğrula (client MIME header'a güvenme)
    kind = _detect_image_kind(data)
    if kind is None:
        raise HTTPException(
            415, "Dosya içeriği tanınmadı (geçerli JPEG/PNG/WEBP/TIFF/PDF değil)",
        )

    result = await extract_text(data, engine="auto")
    # KVKK: çıkarılan metinde TCKN/IBAN/telefon olabilir — sızdırmadan tespit et,
    # metni BOZMA (kullanıcı kendi belgesi; soruyu sormak için tam metne ihtiyaç var).
    # Tespit edilen tür sayıları istemciyi uyarır.
    pii = mask_pii(result.text) if result.text else None
    log.info(
        "ocr_request",
        filename=safe_name, mime=image.content_type, detected_kind=kind,
        engine=result.engine, n_chars=result.n_chars,
        pii_detected=bool(pii and pii.has_pii),
    )
    return OCRUploadResponse(
        text=result.text,
        engine=result.engine,
        n_chars=result.n_chars,
        elapsed_ms=result.elapsed_ms,
        error=result.error,
        pii_detected=bool(pii and pii.has_pii),
        pii_counts=dict(pii.counts) if pii and pii.has_pii else {},
    )


# --------------------------------------------------------------------------
#  STT
# --------------------------------------------------------------------------

@router.post("/stt", response_model=STTUploadResponse)
@limiter.limit("5/minute")  # güvenlik: Whisper inference DoS guard
async def stt_upload(
    request: Request,
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
    # Gerçek dosya türünü magic-byte'lardan doğrula (client MIME header'a güvenme,
    # OCR ile tutarlı). Tanınmazsa 415 — Whisper/ffmpeg'e bozuk içerik gitmesin.
    detected = _detect_audio_kind(data)
    if detected is None:
        raise HTTPException(
            415, "Dosya içeriği tanınmadı (geçerli WAV/MP3/OGG/FLAC/M4A/WebM değil)",
        )

    # Sanitize edilmiş filename'den ext çıkar — whitelist
    ext = "wav"
    if "." in safe_name:
        candidate = safe_name.rsplit(".", 1)[-1].lower()
        if candidate in _ALLOWED_AUDIO_EXTS:
            ext = candidate

    result = await transcribe_audio(data, ext=ext)
    # PII (denetim 2026-06-04): OCR ile SİMETRİK — transkriptte sesli okunan TCKN/telefon/
    # IBAN olabilir; sızdırmadan tespit et, metni BOZMA (kullanıcının kendi girdisi).
    pii = mask_pii(result.text) if result.text else None
    log.info(
        "stt_request",
        filename=safe_name, ext=ext,
        n_chars=len(result.text), duration=result.duration_s,
        pii_detected=bool(pii and pii.has_pii),
    )
    return STTUploadResponse(
        text=result.text,
        language=result.language,
        duration_s=result.duration_s,
        elapsed_ms=result.elapsed_ms,
        error=result.error,
        pii_detected=bool(pii and pii.has_pii),
        pii_counts=dict(pii.counts) if pii and pii.has_pii else {},
    )


# --------------------------------------------------------------------------
#  TTS
# --------------------------------------------------------------------------

@router.post("/tts")
@limiter.limit("10/minute")  # güvenlik: Coqui TTS DoS guard
async def tts_generate(
    request: Request,
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
