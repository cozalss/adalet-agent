"""Bulut TTS — OpenAI (gpt-4o-mini-tts) ile metin → doğal Türkçe ses (WAV).

Lokal Piper'a EK seçenek (v2.3 bulut serbest): belirgin daha doğal Türkçe seslendirme.
`tts.py` auto-routing: OPENAI_API_KEY varsa bulut, yoksa/çağrı patlarsa Piper'a düşer.
stt_cloud/ocr_cloud deseni (raw httpx, openai SDK yok; ortak core.openai_compat).

ENV:
    OPENAI_API_KEY=sk-...              (zorunlu — yoksa RuntimeError → Piper fallback)
    OPENAI_TTS_MODEL=gpt-4o-mini-tts  (default; tts-1 / tts-1-hd de geçerli)
    OPENAI_TTS_VOICE=alloy            (alloy/echo/fable/onyx/nova/shimmer — çok dilli)
    OPENAI_BASE_URL=...               (Azure/proxy override; core.openai_compat doğrular)
"""

from __future__ import annotations

import os

import httpx

from core.openai_compat import (
    cloud_enabled,
    require_api_key,
    send_with_retry,
    validated_base_url,
)

_SPEECH_PATH = "/audio/speech"

# Yanıt boyutu tavanı: kötü/SSRF proxy ya da beklenmedik dev audio worker belleğini şişirmesin.
_MAX_TTS_BYTES = int(os.getenv("OPENAI_TTS_MAX_BYTES", str(10 * 1024 * 1024)))


def cloud_tts_enabled() -> bool:
    """OpenAI anahtarı set mi? (auto-routing kararı için)."""
    return cloud_enabled()


async def synthesize_openai(
    text: str,
    *,
    timeout_s: float,
    model: str | None = None,
    voice: str | None = None,
) -> bytes:
    """OpenAI TTS ile metin → WAV bytes. Başarısızlıkta exception (çağıran Piper'a düşer).
    Anahtar `.env`'den; ASLA hardcode değil."""
    api_key = require_api_key("bulut TTS")
    model = (model or os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")).strip()
    voice = (voice or os.getenv("OPENAI_TTS_VOICE", "alloy")).strip()
    base = validated_base_url()

    payload = {"model": model, "input": text, "voice": voice, "response_format": "wav"}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
        async def _post() -> httpx.Response:
            return await client.post(f"{base}{_SPEECH_PATH}", headers=headers, json=payload)

        resp = await send_with_retry(_post)
        if len(resp.content) > _MAX_TTS_BYTES:
            raise ValueError(f"TTS yanıtı çok büyük: {len(resp.content)} bayt (> {_MAX_TTS_BYTES})")
        return resp.content


__all__ = ("cloud_tts_enabled", "synthesize_openai")
