"""retrieval/mevzuat_client.py — MevzuatClient birim testleri.

MCP JSON-RPC akisi tamamen mock'lanir; dis ag cagrisi yapilmaz.
Kapsam:
- search_kanun_by_no / get_content / get_madde_tree alan fallback'leri
- MCP hata yaniti -> RuntimeError
- JSON decode hatasi -> raw_text fallback
- Tenacity retry (HTTPError sonrasi basari)
- Session ID baslik iletimi
- async with olmadan kullanim -> RuntimeError
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from retrieval.mcp_base import SESSION_HEADER
from retrieval.mevzuat_client import MevzuatClient, MevzuatRef

# ---------------------------------------------------------------------------
# Yardimcilar
# ---------------------------------------------------------------------------

_FAKE_SESSION = "test-session-abc123"


def _mcp_envelope(inner: dict) -> str:
    """_call_tool beklentisiyle MCP yanit zarfi olusturur."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": json.dumps(inner)}]
            },
        }
    )


def _make_http_response(body: str, status: int = 200) -> MagicMock:
    """httpx.Response benzeri sahte nesne dondurur."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    resp.headers = {SESSION_HEADER: _FAKE_SESSION}
    resp.raise_for_status = MagicMock()
    return resp


def _build_client_mock(tool_body: str) -> tuple[MagicMock, MagicMock]:
    """
    httpx.AsyncClient mock'u + post metodu.

    Ilk iki post cagrisi initialize / notifications; ardindan gelen cagrilar
    tool_body dondurur.
    """
    http_client = AsyncMock()
    init_resp = _make_http_response(
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
    )
    notif_resp = _make_http_response("")
    tool_resp = _make_http_response(tool_body)
    http_client.post = AsyncMock(side_effect=[init_resp, notif_resp, tool_resp])
    http_client.aclose = AsyncMock()
    return http_client, http_client.post


async def _run_with_mock(http_client: MagicMock, coro):
    with patch('retrieval.mevzuat_client.httpx.AsyncClient', return_value=http_client):
        async with MevzuatClient() as client:
            return await coro(client)

# ---------------------------------------------------------------------------
# search_kanun_by_no
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_kanun_happy_path():
    """search_kanun_by_no results anahtarindan MevzuatRef listesi olusturur."""
    items = [
        {
            "mevzuat_id": "MK-6502",
            "mevzuat_no": "6502",
            "mevzuat_adi": "Tuketicinin Korunmasi Hakkinda Kanun",
            "mevzuat_tur": "KANUN",
            "resmi_gazete_tarihi": "2013-11-28",
        }
    ]
    body = _mcp_envelope({"results": items})
    http_client, _ = _build_client_mock(body)

    result = await _run_with_mock(http_client, lambda c: c.search_kanun_by_no('6502'))

    assert len(result) == 1
    ref = result[0]
    assert isinstance(ref, MevzuatRef)
    assert ref.mevzuat_id == "MK-6502"
    assert ref.mevzuat_no == "6502"
    assert ref.mevzuat_adi == "Tuketicinin Korunmasi Hakkinda Kanun"
    assert ref.mevzuat_tur == "KANUN"
    assert ref.resmi_gazete_tarihi == "2013-11-28"


@pytest.mark.asyncio
async def test_search_kanun_empty_result():
    """Bos sonuc listesi RuntimeError firlatmadan bos liste dondurur."""
    body = _mcp_envelope({"results": []})
    http_client, _ = _build_client_mock(body)

    result = await _run_with_mock(http_client, lambda c: c.search_kanun_by_no('9999'))

    assert result == []


@pytest.mark.asyncio
async def test_search_kanun_documents_fallback():
    """results yoksa documents anahtari kullanilir."""
    items = [
        {
            "mevzuat_id": "MK-4857",
            "mevzuat_no": "4857",
            "mevzuat_adi": "Is Kanunu",
            "mevzuat_tur": "KANUN",
            "resmi_gazete_tarihi": None,
        }
    ]
    body = _mcp_envelope({"documents": items})
    http_client, _ = _build_client_mock(body)

    result = await _run_with_mock(http_client, lambda c: c.search_kanun_by_no('4857'))

    assert len(result) == 1
    assert result[0].mevzuat_id == "MK-4857"


# ---------------------------------------------------------------------------
# get_content — alan fallback'leri
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_content_markdown_content_field():
    """markdown_content alani birincil onceliğe sahip."""
    body = _mcp_envelope({"markdown_content": "# TKHK"})
    http_client, _ = _build_client_mock(body)

    text = await _run_with_mock(http_client, lambda c: c.get_content('MK-6502'))

    assert text == "# TKHK"


@pytest.mark.asyncio
async def test_get_content_markdown_fallback():
    """markdown_content yoksa markdown alanina duser."""
    body = _mcp_envelope({"markdown": "# Is Kanunu"})
    http_client, _ = _build_client_mock(body)

    text = await _run_with_mock(http_client, lambda c: c.get_content('MK-4857'))

    assert text == "# Is Kanunu"


@pytest.mark.asyncio
async def test_get_content_content_fallback():
    """markdown yoksa content alanina duser."""
    body = _mcp_envelope({"content": "Kanun metni buraya"})
    http_client, _ = _build_client_mock(body)

    text = await _run_with_mock(http_client, lambda c: c.get_content('MK-0001'))

    assert text == "Kanun metni buraya"


@pytest.mark.asyncio
async def test_get_content_text_fallback():
    """content yoksa text alanina duser."""
    body = _mcp_envelope({"text": "Ham metin"})
    http_client, _ = _build_client_mock(body)

    text = await _run_with_mock(http_client, lambda c: c.get_content('MK-0002'))

    assert text == "Ham metin"


@pytest.mark.asyncio
async def test_get_content_empty_when_no_known_field():
    """Hicbir bilinen alan yoksa bos string doner."""
    body = _mcp_envelope({"unknown_field": "deger"})
    http_client, _ = _build_client_mock(body)

    text = await _run_with_mock(http_client, lambda c: c.get_content('MK-0003'))

    assert text == ""

# ---------------------------------------------------------------------------
# get_madde_tree — alan fallback'leri
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_madde_tree_nodes_field():
    """nodes alani birincil onceliğe sahip."""
    nodes = [{"id": "m1", "title": "Madde 1"}, {"id": "m2", "title": "Madde 2"}]
    body = _mcp_envelope({"nodes": nodes})
    http_client, _ = _build_client_mock(body)

    tree = await _run_with_mock(http_client, lambda c: c.get_madde_tree('MK-6502'))

    assert tree == nodes


@pytest.mark.asyncio
async def test_get_madde_tree_tree_fallback():
    """nodes yoksa tree alanina duser."""
    items = [{"id": "m3", "title": "Madde 3"}]
    body = _mcp_envelope({"tree": items})
    http_client, _ = _build_client_mock(body)

    tree = await _run_with_mock(http_client, lambda c: c.get_madde_tree('MK-4857'))

    assert tree == items


@pytest.mark.asyncio
async def test_get_madde_tree_items_fallback():
    """nodes ve tree yoksa items alanina duser."""
    items = [{"id": "m4", "title": "Madde 4"}]
    body = _mcp_envelope({"items": items})
    http_client, _ = _build_client_mock(body)

    tree = await _run_with_mock(http_client, lambda c: c.get_madde_tree('MK-5510'))

    assert tree == items


@pytest.mark.asyncio
async def test_get_madde_tree_empty_fallback():
    """Hicbir bilinen alan yoksa bos liste doner."""
    body = _mcp_envelope({"other": "veri"})
    http_client, _ = _build_client_mock(body)

    tree = await _run_with_mock(http_client, lambda c: c.get_madde_tree('MK-9999'))

    assert tree == []


# ---------------------------------------------------------------------------
# Hata yollari
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_error_raises_runtime():
    """MCP yanitinda error anahtari varsa RuntimeError firlatilmali."""
    error_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32000, "message": "Not found"},
        }
    )
    http_client, _ = _build_client_mock(error_body)

    with pytest.raises(RuntimeError, match="mevzuat-mcp error"):
        await _run_with_mock(http_client, lambda c: c.get_content('MK-MISSING'))


@pytest.mark.asyncio
async def test_json_parse_fallback_raw_text_key_present():
    """JSON decode hatasi: _call_tool raw_text dict dondurur, exception yok."""
    inner_text = "Gecersiz JSON icerigi %%%"
    raw_mcp_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": inner_text}]
            },
        }
    )
    http_client = AsyncMock()
    init_resp = _make_http_response(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}))
    notif_resp = _make_http_response("")
    tool_resp = _make_http_response(raw_mcp_body)
    http_client.post = AsyncMock(side_effect=[init_resp, notif_resp, tool_resp])
    http_client.aclose = AsyncMock()

    with patch('retrieval.mevzuat_client.httpx.AsyncClient', return_value=http_client):
        async with MevzuatClient() as client:
            result = await client._call_tool("get_mevzuat_content", {"mevzuat_id": "X"})

    assert "raw_text" in result
    assert result["raw_text"] == inner_text


@pytest.mark.asyncio
async def test_json_parse_fallback_get_content_returns_empty():
    """JSON decode hatasi sonrasi get_content bilinen alan bulamaz; bos string doner."""
    inner_text = "Bu bir JSON degil."
    raw_mcp_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": inner_text}]
            },
        }
    )
    http_client, _ = _build_client_mock(raw_mcp_body)

    text = await _run_with_mock(http_client, lambda c: c.get_content('MK-RAW'))

    assert text == ""

# ---------------------------------------------------------------------------
# Retry (tenacity)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_on_http_error_succeeds_after_two_failures():
    """Iki HTTPError sonrasi ucuncu denemede basariyla yanit doner."""
    success_body = _mcp_envelope({"markdown_content": "# Basari"})

    http_client = AsyncMock()
    init_resp = _make_http_response(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}))
    notif_resp = _make_http_response("")
    success_resp = _make_http_response(success_body)

    call_count = {"n": 0}

    async def _post_side_effect(*args, **kwargs):
        call_count["n"] += 1
        n = call_count["n"]
        if n == 1:
            return init_resp
        if n == 2:
            return notif_resp
        if n == 3:
            raise httpx.HTTPError("baglanti hatasi")
        if n == 4:
            raise httpx.HTTPError("zaman asimi")
        return success_resp

    http_client.post = AsyncMock(side_effect=_post_side_effect)
    http_client.aclose = AsyncMock()

    with patch('retrieval.mevzuat_client.httpx.AsyncClient', return_value=http_client):
        with patch('tenacity.nap.time.sleep'):
            async with MevzuatClient() as client:
                result = await client.get_content("MK-6502")

    assert result == "# Basari"
    # 1 (init) + 1 (notif) + 2 (fail) + 1 (success) = 5 toplam cagri
    assert call_count["n"] == 5


# ---------------------------------------------------------------------------
# Session ID baslik iletimi
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_header_sent_in_tool_call():
    """Initialize dan alinan session ID her tool cagrisinda baslik olarak gonderilir."""
    body = _mcp_envelope({"markdown_content": "test icerigi"})

    custom_session = "ozel-session-xyz"
    http_client = AsyncMock()
    init_resp = _make_http_response(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}))
    init_resp.headers = {SESSION_HEADER: custom_session}

    notif_resp = _make_http_response("")
    tool_resp = _make_http_response(body)
    tool_resp.headers = {}

    http_client.post = AsyncMock(side_effect=[init_resp, notif_resp, tool_resp])
    http_client.aclose = AsyncMock()

    with patch('retrieval.mevzuat_client.httpx.AsyncClient', return_value=http_client):
        async with MevzuatClient() as client:
            await client.get_content("MK-TEST")

    # Ucuncu cagri (index 2) tool call; headers icinde session ID olmali
    tool_call_kwargs = http_client.post.call_args_list[2].kwargs
    assert tool_call_kwargs.get("headers", {}).get(SESSION_HEADER) == custom_session


# ---------------------------------------------------------------------------
# async with olmadan kullanim guardi
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_session_raises_runtime_error():
    """async with olmadan _call_tool cagrisi RuntimeError firlatir."""
    client = MevzuatClient()  # __aenter__ cagrilmadi -> _client None

    with pytest.raises(RuntimeError):
        await client._call_tool("search_mevzuat", {"mevzuat_no": "6502"})


@pytest.mark.asyncio
async def test_public_method_without_context_raises():
    """async with olmadan search_kanun_by_no cagrisi RuntimeError firlatir."""
    client = MevzuatClient()

    with pytest.raises(RuntimeError):
        await client.search_kanun_by_no("6502")


@pytest.mark.asyncio
async def test_get_content_without_context_raises():
    """async with olmadan get_content cagrisi RuntimeError firlatir."""
    client = MevzuatClient()

    with pytest.raises(RuntimeError):
        await client.get_content("MK-0001")

