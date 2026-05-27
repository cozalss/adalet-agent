"""MCP (Model Context Protocol) ortak yardımcıları — yargi + mevzuat client.

Hem `yargi_client.py` hem `mevzuat_client.py` aynı JSON-RPC 2.0 / SSE protokolünü
konuşur. Protokol sabitleri ve yanıt parser'ı eskiden iki dosyada VERBATIM kopyaydı
(drift riski — biri düzeltilip diğeri unutulabilirdi). Tek kaynağa toplandı.
"""

from __future__ import annotations

import json
from typing import Any

# MCP wire sabitleri — iki client da aynı protokol sürümünü/oturum başlığını kullanır.
PROTOCOL_VERSION = "2024-11-05"
SESSION_HEADER = "mcp-session-id"


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


__all__ = ("PROTOCOL_VERSION", "SESSION_HEADER", "parse_mcp_response")
