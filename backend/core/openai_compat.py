"""OpenAI-uyumlu bulut istemcileri için ORTAK yardımcılar (stt / ocr / tts / llm).

Tek kaynak: anahtar okuma, "bulut açık mı", ve base_url SSRF doğrulaması. Önceden bu mantık
4 modülde kopyaydı (drift riski + ECC DRY bulgusu) → buraya toplandı. Anahtar `.env`'den;
ASLA hardcode değil. base_url operatör-config olsa da env-poisoning'e karşı şema doğrulanır.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    import httpx

_DEFAULT_BASE_URL = "https://api.openai.com/v1"

# Geçici (retry edilebilir) OpenAI HTTP durumları — OpenAIClient.chat ile aynı küme.
# 429 (rate limit) + 5xx (geçici sunucu). 4xx-auth (401/403/400) KALICI → retry yok.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# SSRF: bulut metadata (IMDS) host'ları — kimlik-bilgisi hırsızlığının ana hedefi. Engelle.
# Loopback/private (127.x, 10.x, localhost) MEŞRU bırakılır — yerel OpenAI-uyumlu proxy
# (LiteLLM/Azure gateway) yaygın; yalnız link-local/metadata kapatılır (proportionate).
_BLOCKED_HOSTS = {"metadata.google.internal", "metadata"}
_LINK_LOCAL_NETS = (
    ipaddress.ip_network("169.254.0.0/16"),  # IPv4 link-local + AWS/GCP IMDS
    ipaddress.ip_network("fe80::/10"),       # IPv6 link-local
)


def openai_api_key() -> str:
    """OPENAI_API_KEY (trim'li). Boşsa "" döner."""
    return os.environ.get("OPENAI_API_KEY", "").strip()


def cloud_enabled() -> bool:
    """OpenAI anahtarı set mi? (auto-routing kararı için)."""
    return bool(openai_api_key())


def validated_base_url() -> str:
    """OPENAI_BASE_URL'i şema/host açısından doğrula (SSRF sertleştirme — file://, gopher:// reddet).
    Azure/proxy override için http/https serbest."""
    raw = os.getenv("OPENAI_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"OPENAI_BASE_URL güvensiz: {raw!r}")
    host = (parsed.hostname or "").lower()
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"OPENAI_BASE_URL engellendi (metadata host): {host!r}")
    try:  # IP ise link-local/IMDS aralığını engelle (kimlik-bilgisi hırsızlığı vektörü)
        addr = ipaddress.ip_address(host)
        if any(addr in net for net in _LINK_LOCAL_NETS):
            raise ValueError(f"OPENAI_BASE_URL engellendi (link-local/IMDS): {host!r}")
    except ValueError as exc:
        if "engellendi" in str(exc):
            raise  # bizim engelimiz → yeniden fırlat
        # host bir IP değil (DNS adı) → ipaddress ValueError; normal, devam et
    return raw


def require_api_key(context: str) -> str:
    """Anahtarı döndür; yoksa açıklayıcı RuntimeError (çağıran lokal'e düşebilsin)."""
    key = openai_api_key()
    if not key:
        raise RuntimeError(f"OPENAI_API_KEY yok — {context} devre dışı")
    return key


_RETRY_AFTER_CAP_S = 30.0


def _retry_delay(base_delay: float, attempt: int, response: httpx.Response | None = None) -> float:
    """Exponential backoff; sunucu 429 ile Retry-After verirse ona SAYGI duy (cap'li).

    Retry-After saniye (int) veya HTTP-date olabilir; saniye-int desteklenir, geçersizse backoff.
    Cap (_RETRY_AFTER_CAP_S) kötü-niyetli/aşırı header'ın worker'ı uzun bloke etmesini önler."""
    import contextlib

    delay = base_delay * (2 ** attempt)
    # Retry-After okuması TAMAMEN defansif: header/attr yoksa veya parse edilemezse backoff'a düş
    # (response bir mock/eksik nesne olabilir → asla retry'ı bozma).
    with contextlib.suppress(Exception):
        ra = response.headers.get("retry-after") if response is not None else None
        if ra:
            delay = min(max(delay, float(str(ra).strip())), _RETRY_AFTER_CAP_S)
    return delay


async def send_with_retry(
    do_post: Callable[[], Awaitable[httpx.Response]],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
) -> httpx.Response:
    """Bulut POST'unu geçici hatalarda exponential-backoff ile yeniden dene (STT/OCR/TTS ortak).

    `do_post`: her çağrıda POST yapıp `httpx.Response` döndüren async factory (aynı client'ı
    kapatır → bağlantı havuzu denemeler arası korunur). 429/5xx + ağ hatasında retry; kalıcı
    4xx (auth) HEMEN yükselir. Tüm denemeler tükenince son exception propagate edilir →
    çağıran (stt.py/ocr.py/tts.py) lokal motora graceful düşer. `raise_for_status` burada yapılır.
    """
    import httpx

    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = await do_post()
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            code = exc.response.status_code
            if code in _RETRYABLE_STATUS and attempt < attempts - 1:
                await asyncio.sleep(_retry_delay(base_delay, attempt, exc.response))
                continue
            raise
        except httpx.HTTPError as exc:  # transport/timeout — geçici say
            last_exc = exc
            if attempt < attempts - 1:
                await asyncio.sleep(base_delay * (2 ** attempt))
                continue
            raise
    raise last_exc or RuntimeError("send_with_retry: erişilemez")  # pragma: no cover


__all__ = (
    "cloud_enabled",
    "openai_api_key",
    "require_api_key",
    "send_with_retry",
    "validated_base_url",
)
