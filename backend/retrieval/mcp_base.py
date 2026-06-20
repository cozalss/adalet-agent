"""MCP (Model Context Protocol) ortak yardımcıları — yargi + mevzuat client.

Hem `yargi_client.py` hem `mevzuat_client.py` aynı JSON-RPC 2.0 / SSE protokolünü
konuşur. Protokol sabitleri ve yanıt parser'ı eskiden iki dosyada VERBATIM kopyaydı
(drift riski — biri düzeltilip diğeri unutulabilirdi). Tek kaynağa toplandı.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

# MCP wire sabitleri — iki client da aynı protokol sürümünü/oturum başlığını kullanır.
PROTOCOL_VERSION = "2024-11-05"
SESSION_HEADER = "mcp-session-id"

# Dış MCP yanıtı için üst sınır — bozuk/ele-geçirilmiş sunucu devasa gövdeyle worker
# belleğini tüketmesin (CWE-400 / OWASP A5). 16 MB tüm meşru karar metinleri için fazlasıyla
# yeterli (en uzun Yargıtay/AYM kararları ~1-2 MB). ENV ile ayarlanabilir.
MAX_MCP_RESPONSE_BYTES = int(os.getenv("MCP_MAX_RESPONSE_BYTES", str(16 * 1024 * 1024)))

# base_url için izinli şemalar — `file://`, `gopher://` vb. ile yerel-dosya/protokol
# kötüye kullanımını engelle. Yerel MCP (http://localhost) meşru olduğu için host
# allowlist UYGULANMAZ (private-IP bloğu yerel MCP'yi kırardı) — yalnız şema sıkılaştırması.
_ALLOWED_MCP_SCHEMES = ("http", "https")


def validate_mcp_base_url(url: str) -> str:
    """MCP base_url'i şema açısından doğrula (SSRF/protokol kötüye-kullanım sertleştirmesi).

    Yerel MCP desteği için host kısıtlaması YOK; yalnız http/https şeması zorunlu.
    Geçersiz şema → ValueError (fail-fast, sessiz geçmez).
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_MCP_SCHEMES:
        raise ValueError(
            f"MCP base_url şeması güvensiz: {parsed.scheme!r} "
            f"(izinli: {_ALLOWED_MCP_SCHEMES})"
        )
    if not parsed.netloc:
        raise ValueError(f"MCP base_url host içermiyor: {url!r}")
    return url


def enforce_response_size(
    resp: Any, body: str | None, *, max_bytes: int = MAX_MCP_RESPONSE_BYTES
) -> None:
    """Dış MCP yanıt gövdesi için boyut sınırı uygula (DoS sertleştirmesi).

    İki katman: (1) `Content-Length` header'ı varsa erken reddet, (2) materialize
    edilmiş gövdeyi parser'a vermeden önce uzunluk kontrolü. Sınır aşılırsa ValueError.

    NOT: SSE/chunked yolda gövde okuma sınır kontrolünden ÖNCE gerçekleşir; bu katman
    devasa gövdenin parser'a (json.loads, ~2-3x bellek) geçmesini engeller, okuma anındaki
    tahsisi tamamen önlemez. Tam akış-bazlı sınır için streaming refactor gerekir.
    """
    headers = getattr(resp, "headers", None)
    cl = headers.get("content-length") if hasattr(headers, "get") else None
    if cl is not None:
        try:
            declared = int(cl)
        except (TypeError, ValueError):
            declared = None
        if declared is not None and declared > max_bytes:
            raise ValueError(
                f"MCP yanıt gövdesi sınırı aştı (Content-Length): {declared} > {max_bytes} bayt"
            )
    if body is not None and len(body) > max_bytes:
        raise ValueError(
            f"MCP yanıt gövdesi sınırı aştı: {len(body)} > {max_bytes} bayt"
        )


def parse_mcp_response(body: str) -> dict[str, Any]:
    """MCP yanıtı düz JSON veya SSE chunked olabilir — ikisini de işle.

    - Boş gövde → {} (sunucu bazen 202/empty döner).
    - `{...}` ile başlıyorsa düz JSON.
    - Aksi halde SSE: ilk geçerli `data:` satırını JSON parse et ([DONE] atla).
    """
    body = body.strip()
    if not body:
        return {}

    if body.startswith("{"):
        return json.loads(body)

    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue

    raise ValueError(f"MCP yanıtı parse edilemedi: {body[:200]}")


__all__ = (
    "MAX_MCP_RESPONSE_BYTES",
    "PROTOCOL_VERSION",
    "SESSION_HEADER",
    "enforce_response_size",
    "parse_mcp_response",
    "validate_mcp_base_url",
)
