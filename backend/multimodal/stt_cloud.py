"""Bulut STT — OpenAI gpt-4o-transcribe (en yüksek Türkçe konuşma-tanıma doğruluğu).

Lokal faster-whisper'a EK seçenek (v2.3: lokal-only zorunluluğu kaldırıldı). `stt.py`
auto-routing yapar: `OPENAI_API_KEY` set ise bulut, yoksa/çağrı patlarsa lokal'e düşer.
Ses verisi OpenAI'ye gider (bulut işleme — tam-lokal gizlilik için STT_PROVIDER=local).

ENV:
    OPENAI_API_KEY=sk-...                 (zorunlu — yoksa RuntimeError → lokal fallback)
    OPENAI_STT_MODEL=gpt-4o-transcribe    (default; gpt-4o-mini-transcribe = daha ucuz)
    OPENAI_BASE_URL=https://api.openai.com/v1  (Azure/proxy uyumu için override)
"""

from __future__ import annotations

import os

import httpx

# Uzantı → MIME — OpenAI multipart `file` alanı doğru içerik-tipini ister.
_EXT_MIME = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
    "webm": "audio/webm",
}

_TRANSCRIBE_PATH = "/audio/transcriptions"


def cloud_stt_enabled() -> bool:
    """OpenAI anahtarı set mi? (auto-routing kararı için)."""
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


async def transcribe_openai(
    audio_bytes: bytes,
    *,
    ext: str,
    language: str,
    timeout_s: float,
) -> str:
    """OpenAI gpt-4o-transcribe ile ses → metin döndür.

    Başarısızlıkta (anahtar yok / ağ / 4xx-5xx) exception fırlatır ki çağıran (stt.py)
    lokal'e graceful düşebilsin. Anahtar `.env`'den okunur — ASLA hardcode edilmez.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY yok — bulut STT devre dışı")

    model = os.getenv("OPENAI_STT_MODEL", "gpt-4o-transcribe").strip()
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    mime = _EXT_MIME.get(ext.lower().lstrip("."), "application/octet-stream")

    files = {"file": (f"audio.{ext}", audio_bytes, mime)}
    data = {"model": model, "language": language, "response_format": "json"}
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            f"{base}{_TRANSCRIBE_PATH}", headers=headers, data=data, files=files,
        )
        resp.raise_for_status()
        payload = resp.json()
    return (payload.get("text") or "").strip()


__all__ = ("cloud_stt_enabled", "transcribe_openai")
