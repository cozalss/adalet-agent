"""MCP client precondition guard testleri.

`async with` dışında (init edilmeden) kullanım açık RuntimeError vermeli.
Eskiden `assert` kullanılıyordu → `python -O` (PYTHONOPTIMIZE) ile strip edilir,
guard sessizce kaybolur ve None client'a erişim yanıltıcı AttributeError verirdi.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from retrieval.mcp_base import (
    MAX_MCP_RESPONSE_BYTES,
    enforce_response_size,
    validate_mcp_base_url,
)
from retrieval.mevzuat_client import MevzuatClient
from retrieval.yargi_client import YargiClient


@pytest.mark.asyncio
async def test_yargi_call_tool_without_context_raises_runtime_error():
    client = YargiClient()  # 'async with' YOK → _client None
    with pytest.raises(RuntimeError):
        await client._call_tool("search_yargitay", {})


@pytest.mark.asyncio
async def test_mevzuat_call_tool_without_context_raises_runtime_error():
    client = MevzuatClient()  # 'async with' YOK → _client None
    with pytest.raises(RuntimeError):
        await client._call_tool("search_mevzuat", {})


# ---------------------------------------------------------------------------
# SSRF / DoS sertleştirme guard'ları (kod-inceleme 2026-06-20)
# ---------------------------------------------------------------------------


def test_validate_base_url_rejects_non_http_scheme():
    """file:// gibi şemalar protokol kötüye-kullanımına kapı açar → reddet."""
    with pytest.raises(ValueError):
        validate_mcp_base_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        validate_mcp_base_url("gopher://127.0.0.1:6379/")


def test_validate_base_url_allows_local_and_public():
    """Yerel MCP (http://localhost) ve public (https) MEŞRU — engellenmemeli."""
    assert validate_mcp_base_url("http://127.0.0.1:8765/mcp")
    assert validate_mcp_base_url("https://yargimcp.surucu.dev/mcp")


def test_yargi_client_rejects_unsafe_base_url():
    with pytest.raises(ValueError):
        YargiClient(base_url="file:///etc/passwd")


def test_enforce_response_size_rejects_oversized_body():
    """Devasa gövde parser'a geçmeden ValueError ile reddedilmeli (DoS)."""
    resp = MagicMock()
    resp.headers = {}
    big = "x" * (MAX_MCP_RESPONSE_BYTES + 1)
    with pytest.raises(ValueError, match="sınırı aştı"):
        enforce_response_size(resp, big)


def test_enforce_response_size_rejects_oversized_content_length():
    """Content-Length header'ı sınırı aşıyorsa gövde okunmadan reddet."""
    resp = MagicMock()
    resp.headers = {"content-length": str(MAX_MCP_RESPONSE_BYTES + 100)}
    with pytest.raises(ValueError, match="Content-Length"):
        enforce_response_size(resp, None)


def test_enforce_response_size_allows_normal_body():
    """Normal boyutlu yanıt sorunsuz geçmeli (yanlış-pozitif yok)."""
    resp = MagicMock()
    resp.headers = {"content-length": "1024"}
    enforce_response_size(resp, "ufak karar metni")  # raise etmemeli
