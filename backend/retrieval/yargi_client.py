"""yargi-mcp client — Türk hukuk veritabanlarına MCP JSON-RPC üzerinden erişim.

yargi-mcp bir MCP (Model Context Protocol) sunucusudur. Streamable HTTP
transport kullanır:
  1. POST `initialize` → server `mcp-session-id` header döndürür
  2. POST `notifications/initialized` (session ID ile)
  3. POST `tools/call` (session ID ile)
  4. Yanıtlar SSE formatında (`event: message\ndata: {...}`)

Kullanım:
    async with YargiClient() as client:
        decisions = await client.search_yargitay("mülkiyet", page_size=5)

Repo: https://github.com/saidsurucu/yargi-mcp
Resmi public instance: https://yargimcp.surucu.dev/mcp
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

YARGI_MCP_URL = os.getenv("YARGI_MCP_URL", "https://yargimcp.surucu.dev/mcp")
YARGI_MCP_TIMEOUT_MS = int(os.getenv("YARGI_MCP_TIMEOUT_MS", "30000"))
YARGI_MCP_TOKEN = os.getenv("YARGI_MCP_TOKEN")

PROTOCOL_VERSION = "2024-11-05"
SESSION_HEADER = "mcp-session-id"

CourtType = Literal[
    "YARGITAYKARARI",
    "DANISTAYKARAR",
    "YERELHUKUK",
    "ISTINAFHUKUK",
    "KYB",
]


@dataclass(slots=True)
class YargitayDecision:
    """Tek bir Yargıtay/Danıştay/yerel mahkeme kararı."""

    document_id: str
    court_type: str
    chamber: str | None
    title: str | None
    date: str | None
    summary: str | None
    text: str = ""
    source_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"y-{self.document_id}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "doc_id": self.id,
            "document_id": self.document_id,
            "court": self.court_type,
            "chamber": self.chamber,
            "date": self.date,
            "title": self.title,
            "source": "yargitay",
            "source_url": self.source_url,
        }


class YargiClient:
    """yargi-mcp client. Async kullanım için `async with`."""

    def __init__(
        self,
        base_url: str = YARGI_MCP_URL,
        timeout_ms: int = YARGI_MCP_TIMEOUT_MS,
        token: str | None = YARGI_MCP_TOKEN,
    ) -> None:
        self.base_url = base_url
        self._timeout = timeout_ms / 1000.0
        self._token = token
        self._client: httpx.AsyncClient | None = None
        self._session_id: str | None = None
        self._rpc_id = 0
        self._initialized = False

    async def __aenter__(self) -> YargiClient:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "adalet-agent/0.1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            headers=headers,
            follow_redirects=True,
        )
        await self._initialize_session()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _initialize_session(self) -> None:
        """MCP initialize handshake — session ID'yi yakalar."""
        assert self._client is not None
        self._rpc_id += 1

        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "adalet-agent", "version": "0.1.0"},
            },
            "id": self._rpc_id,
        }

        resp = await self._client.post(self.base_url, json=payload)
        resp.raise_for_status()
        self._session_id = resp.headers.get(SESSION_HEADER)
        if not self._session_id:
            raise RuntimeError("yargi-mcp initialize yanıtında session ID yok")

        envelope = _parse_mcp_response(resp.text)
        if "error" in envelope:
            raise RuntimeError(f"initialize hatası: {envelope['error']}")

        await self._send_notification("notifications/initialized", {})
        self._initialized = True
        logger.info("yargi_mcp_initialized", extra={"session_id": self._session_id})

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Notification gönder — id yok, yanıt beklenmez."""
        assert self._client is not None and self._session_id is not None
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._client.post(
            self.base_url,
            json=payload,
            headers={SESSION_HEADER: self._session_id},
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """MCP tools/call wrapper. Tool sonucundaki JSON metni parse eder."""
        assert self._client is not None, "YargiClient must be used via 'async with'"
        assert self._session_id, "Session ilk olarak _initialize_session ile kurulmalı"

        self._rpc_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": self._rpc_id,
        }

        resp = await self._client.post(
            self.base_url,
            json=payload,
            headers={SESSION_HEADER: self._session_id},
        )
        resp.raise_for_status()
        envelope = _parse_mcp_response(resp.text)

        if "error" in envelope:
            err = envelope["error"]
            raise RuntimeError(f"yargi-mcp hata: {err.get('message')} ({err})")

        result = envelope.get("result", {})
        content = result.get("content") or []
        if not content:
            return {}

        first = content[0]
        text = first.get("text", "")
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw_text": text}

    async def search_yargitay(
        self,
        phrase: str,
        page_size: int = 10,
        page_number: int = 1,
        chamber: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
    ) -> list[YargitayDecision]:
        """Yargıtay kararı arama (Bedesten unified API üzerinden)."""
        return await self._search_court(
            ["YARGITAYKARARI"],
            phrase=phrase,
            page_size=page_size,
            page_number=page_number,
            chamber=chamber,
            date_start=date_start,
            date_end=date_end,
        )

    async def search_danistay(
        self,
        phrase: str,
        page_size: int = 10,
        page_number: int = 1,
        chamber: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
    ) -> list[YargitayDecision]:
        return await self._search_court(
            ["DANISTAYKARAR"],
            phrase=phrase,
            page_size=page_size,
            page_number=page_number,
            chamber=chamber,
            date_start=date_start,
            date_end=date_end,
        )

    async def _search_court(
        self,
        court_types: list[CourtType],
        *,
        phrase: str,
        page_size: int,
        page_number: int,
        chamber: str | None,
        date_start: str | None,
        date_end: str | None,
    ) -> list[YargitayDecision]:
        # NOT: yargi-mcp v0.2.0+ search_bedesten_unified pageSize parametresi YOK
        # (token optimizasyon fazlarında kaldırıldı). Sadece pageNumber kabul edilir,
        # sayfa boyutu sunucu tarafından belirlenir.
        _ = page_size  # API'ye gönderilmez — kullanıcı kodundaki imzayı koruyoruz
        arguments: dict[str, Any] = {
            "phrase": phrase,
            "court_types": court_types,
            "pageNumber": max(page_number, 1),
        }
        if chamber:
            arguments["birimAdi"] = chamber
        if date_start:
            arguments["kararTarihiStart"] = date_start
        if date_end:
            arguments["kararTarihiEnd"] = date_end

        logger.info(
            "yargi_search_started",
            extra={"court_types": court_types, "phrase": phrase, "page": page_number},
        )

        data = await self._call_tool("search_bedesten_unified", arguments)
        decisions_raw = (
            data.get("decisions")
            or data.get("results")
            or (data.get("data") or {}).get("emsalKararList")
            or []
        )

        decisions: list[YargitayDecision] = []
        for item in decisions_raw:
            try:
                decisions.append(_parse_decision(item, court_types[0]))
            except ValueError as exc:
                logger.warning("decision_parse_skipped", extra={"err": str(exc)})
        logger.info("yargi_search_completed", extra={"count": len(decisions)})
        return decisions

    async def get_document(self, document_id: str) -> str:
        """Karar tam metnini (Markdown) çek."""
        data = await self._call_tool(
            "get_bedesten_document_markdown",
            {"documentId": document_id},
        )
        return (
            data.get("markdown_content")
            or data.get("markdown")
            or data.get("text")
            or ""
        )

    async def search_anayasa(
        self,
        keywords: list[str],
        decision_type: Literal["norm_denetimi", "bireysel_basvuru"] = "bireysel_basvuru",
        page_to_fetch: int = 1,
    ) -> list[YargitayDecision]:
        """Anayasa Mahkemesi kararı arama (norm denetimi veya bireysel başvuru)."""
        arguments: dict[str, Any] = {
            "decision_type": decision_type,
            "page_to_fetch": max(page_to_fetch, 1),
        }
        if keywords:
            arguments["keywords"] = keywords

        logger.info(
            "anayasa_search_started",
            extra={"decision_type": decision_type, "keywords": keywords, "page": page_to_fetch},
        )

        data = await self._call_tool("search_anayasa_unified", arguments)
        decisions_raw = (
            data.get("decisions")
            or data.get("results")
            or (data.get("data") or {}).get("decisions")
            or []
        )

        decisions: list[YargitayDecision] = []
        for item in decisions_raw:
            try:
                decisions.append(_parse_anayasa_decision(item, decision_type))
            except ValueError as exc:
                logger.warning("anayasa_parse_skipped", extra={"err": str(exc)})
        logger.info("anayasa_search_completed", extra={"count": len(decisions)})
        return decisions

    async def get_anayasa_document(self, document_url: str, max_pages: int = 5) -> str:
        """Anayasa kararının tam metnini (Markdown) çek.

        Anayasa belgeleri 5000 karakterlik sayfalara bölünmüştür — birden fazla
        sayfa varsa hepsini birleştirir.
        """
        all_text: list[str] = []
        for page_num in range(1, max_pages + 1):
            data = await self._call_tool(
                "get_anayasa_document_unified",
                {"document_url": document_url, "page_number": page_num},
            )
            # yargi-mcp v0.2.x: top-level `markdown_chunk` + `total_pages`
            text = (
                data.get("markdown_chunk")
                or data.get("markdown_content")
                or data.get("markdown")
                or data.get("text")
                or ""
            )
            if not text:
                break
            all_text.append(text)

            total_pages = data.get("total_pages") or 1
            if page_num >= int(total_pages):
                break

        return "\n\n".join(all_text)


def _parse_mcp_response(body: str) -> dict[str, Any]:
    """MCP yanıtı düz JSON veya SSE chunked olabilir — ikisini de işle."""
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


_DATE_FORMATS = (
    "%d.%m.%Y",   # Yargıtay/Danıştay Bedesten: 01.01.2024
    "%d/%m/%Y",   # Anayasa: 02/05/2024
    "%Y-%m-%d",   # ISO
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%fZ",
)


def _normalize_date(raw: str | None) -> str | None:
    """Heterojen tarih formatlarını ISO 8601 (YYYY-MM-DD) standardına çevir.

    Yargıtay/Danıştay "DD.MM.YYYY", Anayasa "DD/MM/YYYY" formatında döner.
    Qdrant'ta lexicographic karşılaştırma yapacaksa ISO format şart.
    None / parse edilemeyen değerleri olduğu gibi bırakır.
    """
    if not raw or not isinstance(raw, str):
        return raw
    raw = raw.strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    logger.debug("date_parse_failed", extra={"raw": raw[:60]})
    return raw  # Orijinali döndür — Qdrant'a yine de yazılsın, kullanıcı görsün


def _normalize_url(url: str) -> str:
    """URL'leri dedupe için kanonik forma getir — trailing slash, query, fragment strip."""
    if not url:
        return ""
    url = url.strip().split("#")[0].split("?")[0]
    return url.rstrip("/")


def _parse_decision(item: dict[str, Any], court_type: str) -> YargitayDecision:
    """yargi-mcp ham karar JSON → YargitayDecision (Bedesten).

    Empty document_id reddedilir — phantom chunk + UUID5 collision'u engeller.
    """
    doc_id = str(item.get("documentId") or item.get("id") or "").strip()
    if not doc_id:
        raise ValueError(f"Bedesten karar 'documentId' eksik: court={court_type}")
    return YargitayDecision(
        document_id=doc_id,
        court_type=item.get("courtType") or court_type,
        chamber=item.get("birimAdi") or item.get("chamber"),
        title=item.get("title") or item.get("baslik"),
        date=_normalize_date(item.get("kararTarihi") or item.get("date")),
        summary=item.get("summary") or item.get("ozet"),
        text=item.get("content") or item.get("text") or "",
        source_url=item.get("url") or item.get("source_url") or "",
        raw=item,
    )


def _parse_anayasa_decision(item: dict[str, Any], decision_type: str) -> YargitayDecision:
    """Anayasa ham karar JSON → YargitayDecision.

    yargi-mcp v0.2.x bireysel_basvuru response field isimleri:
    - decision_page_url      → tam URL (get_anayasa_document_unified `document_url` parametresi)
    - decision_reference_no  → "2024/28913" benzersiz başvuru no
    - decision_date_summary  → "02/05/2024" gibi
    - decision_making_body   → "Genel Kurul" / "Komisyon" / "Esas (İhlal)" — chamber alanı
    - title                  → karar başlığı
    """
    document_url = _normalize_url(
        item.get("decision_page_url")
        or item.get("document_url")
        or item.get("url")
        or ""
    )
    reference_no = (
        item.get("decision_reference_no")
        or item.get("application_no")
        or document_url
    )
    if not reference_no:
        raise ValueError("Anayasa karar 'decision_reference_no' veya URL eksik")
    return YargitayDecision(
        document_id=str(reference_no),  # "2024/28913" — benzersiz başvuru numarası
        court_type=f"ANAYASA_{decision_type.upper()}",
        chamber=item.get("decision_making_body") or item.get("daire"),
        title=item.get("title") or item.get("baslik"),
        date=_normalize_date(item.get("decision_date_summary") or item.get("decision_date")),
        summary=item.get("application_subject_summary") or item.get("ozet"),
        text="",  # Tam metin get_anayasa_document ile ayrıca çekilir
        source_url=document_url,
        raw=item,
    )
