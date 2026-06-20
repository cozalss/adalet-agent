"""OpenAI-uyumlu bulut istemcileri için ORTAK yardımcılar (stt / ocr / tts / llm).

Tek kaynak: anahtar okuma, "bulut açık mı", ve base_url SSRF doğrulaması. Önceden bu mantık
4 modülde kopyaydı (drift riski + ECC DRY bulgusu) → buraya toplandı. Anahtar `.env`'den;
ASLA hardcode değil. base_url operatör-config olsa da env-poisoning'e karşı şema doğrulanır.
"""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse

_DEFAULT_BASE_URL = "https://api.openai.com/v1"

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


__all__ = (
    "cloud_enabled",
    "openai_api_key",
    "require_api_key",
    "validated_base_url",
)
