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

from core.openai_compat import cloud_enabled, require_api_key, send_with_retry
from core.openai_compat import validated_base_url as _validated_base_url

# Ön-yükleme boyut kıskacı: OpenAI Whisper 25MB üstünü reddeder; ondan ÖNCE yerel kapı —
# büyük blob'u boşuna yükleyip bant-genişliği/kısmi maliyet harcama. OPENAI_STT_MAX_BYTES ile ayar.
_MAX_AUDIO_BYTES = int(os.getenv("OPENAI_STT_MAX_BYTES", str(24 * 1024 * 1024)))

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
    """OpenAI anahtarı set mi? (auto-routing kararı için — ortak helper)."""
    return cloud_enabled()


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
    api_key = require_api_key("bulut STT")
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise ValueError(f"Ses dosyası çok büyük: {len(audio_bytes)} bayt (> {_MAX_AUDIO_BYTES})")

    model = os.getenv("OPENAI_STT_MODEL", "gpt-4o-transcribe").strip()
    base = _validated_base_url()
    mime = _EXT_MIME.get(ext.lower().lstrip("."), "application/octet-stream")

    data = {"model": model, "language": language, "response_format": "json"}
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
        # files= her denemede yeniden kurulur (stream tüketimi sonrası retry'da boş kalmasın).
        async def _post() -> httpx.Response:
            return await client.post(
                f"{base}{_TRANSCRIBE_PATH}", headers=headers, data=data,
                files={"file": (f"audio.{ext}", audio_bytes, mime)},
            )

        resp = await send_with_retry(_post)
        payload = resp.json()
    return (payload.get("text") or "").strip()


__all__ = ("cloud_stt_enabled", "transcribe_openai")
