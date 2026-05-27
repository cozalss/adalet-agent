"""retrieval/mcp_base.py — ortak MCP parser/sabit testleri.

Eskiden yargi_client + mevzuat_client'ta verbatim kopyaydı; tek kaynağa
toplandı. Bu testler parser davranışını (JSON / SSE / boş / [DONE]) sabitler.
"""

from __future__ import annotations

import pytest

from retrieval.mcp_base import (
    PROTOCOL_VERSION,
    SESSION_HEADER,
    parse_mcp_response,
)


def test_constants():
    assert PROTOCOL_VERSION == "2024-11-05"
    assert SESSION_HEADER == "mcp-session-id"


def test_parse_empty_returns_empty_dict():
    assert parse_mcp_response("") == {}
    assert parse_mcp_response("   ") == {}


def test_parse_plain_json():
    out = parse_mcp_response('{"result": {"ok": 1}}')
    assert out == {"result": {"ok": 1}}


def test_parse_sse_data_line():
    body = 'event: message\ndata: {"result": {"x": 2}}\n\n'
    assert parse_mcp_response(body) == {"result": {"x": 2}}


def test_parse_sse_skips_done_sentinel():
    body = 'data: [DONE]\ndata: {"result": 3}\n'
    assert parse_mcp_response(body) == {"result": 3}


def test_parse_unparseable_raises():
    with pytest.raises(ValueError, match="parse edilemedi"):
        parse_mcp_response("event: message\ndata: not-json\n")
