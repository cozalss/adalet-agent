"""retrieval/yargi_client.py -- YargiClient birim testleri.

Strateji:
  - YargiClient._call_tool dogrudan patch edilir; gercek ag cagrisi olmaz.
  - _initialize_session da patch edilir -- handshake beklenmez.
  - asyncio.sleep patch edilir -- rate_limit testinde gercek bekleme olmaz.
  - HTTPError senaryosunda tenacity gercek 3 deneme yapar (post mock sirayla fail/success).
  - Session ID testi icin httpx.AsyncClient modul duzeyi patch kullanilir.
  - AAA (Arrange / Act / Assert) duzeni her testte korunur.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from retrieval.mcp_base import SESSION_HEADER
from retrieval.yargi_client import (
    RegulatorDecision,
    YargitayDecision,
    YargiClient,
)

_SESSION_ID = "test-session-yargi-xyz"

# ---------------------------------------------------------------------------
# Ham veri sabitleri
# ---------------------------------------------------------------------------

_YARGITAY_ITEM = {
    "documentId": "DOC-001",
    "courtType": "YARGITAYKARARI",
    "birimAdi": "12. Hukuk Dairesi",
    "title": "Mulkiyet ihlali emsal karari",
    "kararTarihi": "15.03.2023",
    "summary": "Tapu iptali ve tescil",
    "url": "https://yargitay.gov.tr/karar/DOC-001",
}

_EMSAL_ITEM = {
    "id": "EMSAL-42",
    "daire": "Bolge Adliye 3. HD",
    "esasNo": "2022/1000",
    "kararNo": "2023/500",
    "kararTarihi": "20.06.2023",
    "durum": "Kesinlesti",
    "document_url": "https://emsal.uyap.gov.tr/karar/42",
}

_ANAYASA_ITEM = {
    "decision_page_url": "https://anayasa.gov.tr/bireysel/2024-28913",
    "decision_reference_no": "2024/28913",
    "decision_date_summary": "02/05/2024",
    "decision_making_body": "Genel Kurul",
    "title": "Ozel hayatin gizliligi",
    "application_subject_summary": "Iletisimin denetlenmesi",
}

_KVKK_ITEM = {
    "decision_id": "KVKK-2024-001",
    "title": "Kisisel veri ihlali karari",
    "decision_date": "2024-01-15",
    "summary": "Veri sorumlusu ihlali",
    "decision_url": "https://kvkk.gov.tr/karar/001",
}

_REKABET_ITEM = {
    "karar_id": "RK-2023-050",
    "title": "Hakim durum tespiti",
    "karar_tarihi": "2023-11-01",
    "summary": "4054 sayili Kanun ihlali",
}

_SAYISTAY_ITEM = {
    "id": "SAY-789",
    "web_karar_konusu": "Kamu alimi usulsuzlugu",
    "kamu_idaresi_turu": "Belediye",
    "karar_tarihi": "2023-09-10",
}


# ---------------------------------------------------------------------------
# Yardimci
# ---------------------------------------------------------------------------

def _mcp_envelope(inner: dict) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": json.dumps(inner)}]},
        }
    )


def _make_http_response(body: str, session: str = _SESSION_ID) -> MagicMock:
    resp = MagicMock()
    resp.text = body
    resp.headers = {SESSION_HEADER: session}
    resp.raise_for_status = MagicMock()
    return resp


def _build_http_client(tool_inner: dict) -> tuple:
    http_client = AsyncMock()
    init_resp = _make_http_response(
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
    )
    notif_resp = _make_http_response("")
    tool_resp = _make_http_response(_mcp_envelope(tool_inner))
    http_client.post = AsyncMock(side_effect=[init_resp, notif_resp, tool_resp])
    http_client.aclose = AsyncMock()
    return http_client, http_client.post


def _ready_client() -> YargiClient:
    c = YargiClient()
    c._client = AsyncMock()
    c._session_id = _SESSION_ID
    c._initialized = True
    return c


# ---------------------------------------------------------------------------
# 1. search_yargitay -- happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_yargitay_happy_path():
    # Arrange
    with patch.object(YargiClient, "_call_tool", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = {"decisions": [_YARGITAY_ITEM]}
        client = _ready_client()

        # Act
        results = await client.search_yargitay("mulkiyet")

    # Assert
    assert len(results) == 1
    dec = results[0]
    assert isinstance(dec, YargitayDecision)
    assert dec.document_id == "DOC-001"
    assert dec.court_type == "YARGITAYKARARI"
    assert dec.chamber == "12. Hukuk Dairesi"
    assert dec.date == "2023-03-15"
    assert dec.source_url == "https://yargitay.gov.tr/karar/DOC-001"
    mock_ct.assert_called_once()
    tool_name, tool_args = mock_ct.call_args[0]
    assert tool_name == "search_bedesten_unified"
    assert tool_args["court_types"] == ["YARGITAYKARARI"]
    assert tool_args["phrase"] == "mulkiyet"


# ---------------------------------------------------------------------------
# 2. search_yargitay -- chamber parametresi iletilir
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_yargitay_with_chamber():
    # Arrange
    with patch.object(YargiClient, "_call_tool", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = {"decisions": []}
        client = _ready_client()

        # Act
        await client.search_yargitay("kira", chamber="4. Hukuk Dairesi")

    # Assert
    args = mock_ct.call_args[0][1]
    assert args["birimAdi"] == "4. Hukuk Dairesi"


# ---------------------------------------------------------------------------
# 3. search_yargitay -- tarih araligi iletilir
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_yargitay_with_date_range():
    # Arrange
    with patch.object(YargiClient, "_call_tool", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = {"decisions": []}
        client = _ready_client()

        # Act
        await client.search_yargitay(
            "tapu", date_start="01.01.2023", date_end="31.12.2023"
        )

    # Assert
    args = mock_ct.call_args[0][1]
    assert args["kararTarihiStart"] == "01.01.2023"
    assert args["kararTarihiEnd"] == "31.12.2023"


# ---------------------------------------------------------------------------
# 4. search_emsal -- happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_emsal_happy_path():
    # Arrange
    with patch.object(YargiClient, "_call_tool", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = {"decisions": [_EMSAL_ITEM]}
        client = _ready_client()

        # Act
        results = await client.search_emsal("ayipli mal")

    # Assert
    assert len(results) == 1
    dec = results[0]
    assert isinstance(dec, YargitayDecision)
    assert dec.document_id == "EMSAL-42"
    assert dec.court_type == "emsal"
    assert dec.chamber == "Bolge Adliye 3. HD"
    assert mock_ct.call_args[0][0] == "search_emsal_detailed_decisions"
    assert mock_ct.call_args[0][1]["keyword"] == "ayipli mal"


# ---------------------------------------------------------------------------
# 5. search_anayasa -- bireysel_basvuru decision_type iletilir
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_anayasa_bireysel_basvuru():
    # Arrange
    with patch.object(YargiClient, "_call_tool", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = {"decisions": [_ANAYASA_ITEM]}
        client = _ready_client()

        # Act
        results = await client.search_anayasa(
            ["ozel hayat", "iletisim"], decision_type="bireysel_basvuru"
        )

    # Assert
    assert len(results) == 1
    dec = results[0]
    assert isinstance(dec, YargitayDecision)
    assert dec.document_id == "2024/28913"
    assert dec.court_type == "ANAYASA_BIREYSEL_BASVURU"
    assert dec.chamber == "Genel Kurul"
    assert dec.date == "2024-05-02"
    tool_name, tool_args = mock_ct.call_args[0]
    assert tool_name == "search_anayasa_unified"
    assert tool_args["decision_type"] == "bireysel_basvuru"
    assert "ozel hayat" in tool_args["keywords"]


# ---------------------------------------------------------------------------
# 6. search_kvkk -- regulator field "kvkk"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_kvkk_returns_regulator_decisions():
    # Arrange
    with patch.object(YargiClient, "_call_tool", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = {"decisions": [_KVKK_ITEM]}
        client = _ready_client()

        # Act
        results = await client.search_kvkk("kisisel veri")

    # Assert
    assert len(results) == 1
    dec = results[0]
    assert isinstance(dec, RegulatorDecision)
    assert dec.regulator == "kvkk"
    assert dec.decision_id == "KVKK-2024-001"
    assert mock_ct.call_args[0][0] == "search_kvkk_decisions"
    assert mock_ct.call_args[0][1]["keywords"] == "kisisel veri"


# ---------------------------------------------------------------------------
# 7. search_rekabet -- PdfText parametresi set edilir
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_rekabet_with_keyword():
    # Arrange
    with patch.object(YargiClient, "_call_tool", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = {"decisions": [_REKABET_ITEM]}
        client = _ready_client()

        # Act
        results = await client.search_rekabet(keyword="hakim durum")

    # Assert
    assert len(results) == 1
    assert results[0].regulator == "rekabet"
    assert results[0].decision_id == "RK-2023-050"
    assert mock_ct.call_args[0][0] == "search_rekabet_kurumu_decisions"
    assert mock_ct.call_args[0][1]["PdfText"] == "hakim durum"


# ---------------------------------------------------------------------------
# 8. search_sayistay -- start = (page-1) * length pagination formulu
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_sayistay_daire():
    # Arrange
    with patch.object(YargiClient, "_call_tool", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = {"decisions": [_SAYISTAY_ITEM]}
        client = _ready_client()

        # Act -- page=3, length=20 -> start=40
        results = await client.search_sayistay(
            "kamu alimi", decision_type="daire", page=3, length=20
        )

    # Assert
    assert len(results) == 1
    assert results[0].regulator == "sayistay"
    args = mock_ct.call_args[0][1]
    assert args["start"] == 40
    assert args["length"] == 20
    assert args["decision_type"] == "daire"
    assert args["web_karar_metni"] == "kamu alimi"
    assert mock_ct.call_args[0][0] == "search_sayistay_unified"


# ---------------------------------------------------------------------------
# 9. get_document -- markdown_content -> markdown -> text fallback zinciri
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_document_markdown_fallback_chain():
    # Arrange
    with patch.object(YargiClient, "_call_tool", new_callable=AsyncMock) as mock_ct:
        client = _ready_client()

        mock_ct.return_value = {"markdown_content": "## Karar A"}
        result_a = await client.get_document("DOC-001")

        mock_ct.return_value = {"markdown": "## Karar B"}
        result_b = await client.get_document("DOC-002")

        mock_ct.return_value = {"text": "Karar C"}
        result_c = await client.get_document("DOC-003")

        mock_ct.return_value = {}
        result_d = await client.get_document("DOC-004")

    # Assert
    assert result_a == "## Karar A"
    assert result_b == "## Karar B"
    assert result_c == "Karar C"
    assert result_d == ""


# ---------------------------------------------------------------------------
# 10. get_regulator_document -- kvkk dogru tool ve argument key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_regulator_document_kvkk():
    # Arrange
    with patch.object(YargiClient, "_call_tool", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = {"markdown_content": "KVKK karar tam metin"}
        client = _ready_client()

        # Act
        result = await client.get_regulator_document(
            "kvkk", "https://kvkk.gov.tr/karar/001"
        )

    # Assert
    assert result == "KVKK karar tam metin"
    tool_name, tool_args = mock_ct.call_args[0]
    assert tool_name == "get_kvkk_document_markdown"
    assert tool_args == {"decision_url": "https://kvkk.gov.tr/karar/001"}


# ---------------------------------------------------------------------------
# 11. get_regulator_document -- rekabet dogru tool ve argument key
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_regulator_document_rekabet():
    # Arrange
    with patch.object(YargiClient, "_call_tool", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = {"markdown": "Rekabet karari metni"}
        client = _ready_client()

        # Act
        result = await client.get_regulator_document("rekabet", "RK-2023-050")

    # Assert
    assert result == "Rekabet karari metni"
    tool_name, tool_args = mock_ct.call_args[0]
    assert tool_name == "get_rekabet_kurumu_document"
    assert tool_args == {"karar_id": "RK-2023-050"}


# ---------------------------------------------------------------------------
# 12. get_regulator_document -- bilinmeyen regulator -> ValueError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_regulator_document_unknown_raises():
    # Arrange
    client = _ready_client()

    # Act & Assert
    with pytest.raises(ValueError, match="Unknown regulator"):
        await client.get_regulator_document("mahkeme_bilinmeyen", "REF-999")


# ---------------------------------------------------------------------------
# 13. rate_limit_exceeded -> sleep -> retry -> basari
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limit_retry():
    # Arrange
    rate_limit_resp = {"error": "rate_limit_exceeded", "retry_after": "3"}
    success_resp = {"decisions": [_YARGITAY_ITEM]}

    client = _ready_client()
    call_count = 0

    async def _side_effect(tool_name, arguments):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return rate_limit_resp
        return success_resp

    with patch.object(YargiClient, "_call_tool", side_effect=_side_effect):
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # Act
            results = await client.search_yargitay("mulkiyet")

    # Assert
    assert call_count == 2
    mock_sleep.assert_called_once_with(4.0)
    assert len(results) == 1
    assert results[0].document_id == "DOC-001"


# ---------------------------------------------------------------------------
# 14. MCP error yaniti -> RuntimeError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_error_raises_runtime():
    """_call_tool: MCP envelope'da error key varsa RuntimeError firlatir."""
    # Arrange
    client = _ready_client()

    error_envelope = {
        "jsonrpc": "2.0",
        "error": {"code": -32600, "message": "Invalid request"},
        "id": 1,
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = json.dumps(error_envelope)
    client._client.post = AsyncMock(return_value=mock_resp)

    # Act & Assert
    with pytest.raises(RuntimeError, match="yargi-mcp hata"):
        await client._call_tool("search_bedesten_unified", {"phrase": "test"})


# ---------------------------------------------------------------------------
# 15. HTTPError -> tenacity retry -> basari
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_on_http_error():
    """Ilk 2 post raise_for_status HTTPStatusError firlatir; 3. basarili."""
    # Arrange
    client = _ready_client()

    success_inner = {"decisions": [_YARGITAY_ITEM]}
    success_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "result": {
                "content": [{"type": "text", "text": json.dumps(success_inner)}]
            },
            "id": 2,
        }
    )

    http_error = httpx.HTTPStatusError(
        "500 Internal Server Error",
        request=MagicMock(),
        response=MagicMock(),
    )

    call_count = 0

    async def _flaky_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        if call_count <= 2:
            resp.raise_for_status = MagicMock(side_effect=http_error)
        else:
            resp.raise_for_status = MagicMock()
            resp.text = success_body
        return resp

    client._client.post = _flaky_post

    # Act -- tenacity stop_after_attempt(3); ilk 2 fail, 3. gecmeli
    result = await client._call_tool("search_bedesten_unified", {"phrase": "test"})

    # Assert
    assert call_count == 3
    assert result["decisions"][0]["documentId"] == "DOC-001"


# ---------------------------------------------------------------------------
# 16. mcp-session-id header sonraki cagrilarda iletilir
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_id_sent_in_subsequent_calls():
    """Tool/call post cagrisinda mcp-session-id header tasimali."""
    # Arrange
    http_client, mock_post = _build_http_client({"decisions": []})

    with patch("retrieval.yargi_client.httpx.AsyncClient", return_value=http_client):
        async with YargiClient(base_url="https://test.local/mcp") as client:
            # Act
            await client.search_yargitay("kira")

    # Assert -- tool/call post (3. cagri, index 2) session header tasimali
    all_calls = mock_post.call_args_list
    assert len(all_calls) >= 3
    tool_call = all_calls[2]
    headers = tool_call[1].get("headers", {}) if tool_call[1] else {}
    assert headers.get(SESSION_HEADER) == _SESSION_ID
