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

from retrieval.mcp_base import (
    PROTOCOL_VERSION,
    SESSION_HEADER,
    enforce_response_size,
    parse_mcp_response,
    validate_mcp_base_url,
)

logger = logging.getLogger(__name__)

YARGI_MCP_URL = os.getenv("YARGI_MCP_URL", "https://yargimcp.surucu.dev/mcp")
YARGI_MCP_TIMEOUT_MS = int(os.getenv("YARGI_MCP_TIMEOUT_MS", "30000"))
YARGI_MCP_TOKEN = os.getenv("YARGI_MCP_TOKEN")

# Dış MCP sunucusunun döndürdüğü rate-limit `retry_after` GÜVENİLMEZ veridir; üst
# sınır olmadan doğrudan asyncio.sleep'e beslemek DoS yüzeyidir (kötü/hatalı sunucu
# devasa değer döndürüp isteği süresiz askıya alabilir). Bu tavanla sıkıştırılır.
_MAX_RETRY_AFTER_S = 60.0

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


@dataclass(slots=True)
class RegulatorDecision:
    """Tek bir düzenleyici otorite kararı (KVKK / Rekabet / Sayıştay / BDDK / GİB)."""

    regulator: str  # kvkk, rekabet, sayistay, bddk, gib_ozelge, sigorta_tahkim, kik
    decision_id: str
    title: str | None
    date: str | None
    summary: str | None
    text: str = ""
    source_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"reg-{self.regulator}-{self.decision_id}"


class YargiClient:
    """yargi-mcp client. Async kullanım için `async with`."""

    def __init__(
        self,
        base_url: str = YARGI_MCP_URL,
        timeout_ms: int = YARGI_MCP_TIMEOUT_MS,
        token: str | None = YARGI_MCP_TOKEN,
    ) -> None:
        self.base_url = validate_mcp_base_url(base_url)
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
            # SSRF sertleştirme (CWE-918): ele-geçirilmiş/hatalı MCP sunucusu 3xx ile
            # iç ağ adreslerine (169.254.169.254 metadata, localhost servisleri) yönlendirip
            # allowlist'i bypass edemesin. MCP Streamable HTTP redirect KULLANMAZ.
            follow_redirects=False,
        )
        await self._initialize_session()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _initialize_session(self) -> None:
        """MCP initialize handshake — session ID'yi yakalar."""
        # NOT: assert KULLANMA — `python -O` (PYTHONOPTIMIZE) ile strip edilir,
        # guard sessizce kaybolur → None'a erişim yanıltıcı AttributeError verir.
        if self._client is None:
            raise RuntimeError("YargiClient 'async with' bloğunda kullanılmalı")
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

        enforce_response_size(resp, resp.text)
        envelope = parse_mcp_response(resp.text)
        if "error" in envelope:
            raise RuntimeError(f"initialize hatası: {envelope['error']}")

        await self._send_notification("notifications/initialized", {})
        self._initialized = True
        logger.info("yargi_mcp_initialized", extra={"session_id": self._session_id})

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Notification gönder — id yok, yanıt beklenmez."""
        if self._client is None or self._session_id is None:
            raise RuntimeError("YargiClient: session başlatılmadı (_initialize_session)")
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
        if self._client is None:
            raise RuntimeError("YargiClient 'async with' ile kullanılmalı")
        if not self._session_id:
            raise RuntimeError("YargiClient: session önce _initialize_session ile kurulmalı")

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
        enforce_response_size(resp, resp.text)
        envelope = parse_mcp_response(resp.text)

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
        # Sprint-5 W13 fix: yargi-mcp 0.2.0 rate_limit_exceeded → 429 status,
        # retry_after saniye field. Bekleme + 1 retry yap.
        if data.get("error") == "rate_limit_exceeded":
            # Dış-servis verisi: sayı değilse güvenli varsayılan (float() çökmesini önle),
            # sonra [0, _MAX_RETRY_AFTER_S] aralığına sıkıştır (sınırsız sleep = DoS).
            try:
                retry_after_s = float(data.get("retry_after", "5") or 5)
            except (TypeError, ValueError):
                retry_after_s = 5.0
            retry_after_s = max(0.0, min(retry_after_s, _MAX_RETRY_AFTER_S))
            logger.info(
                "yargi_rate_limited_retry",
                extra={"retry_after": retry_after_s, "phrase": phrase},
            )
            import asyncio as _asyncio
            await _asyncio.sleep(retry_after_s + 1)
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

    async def search_emsal(
        self,
        keyword: str,
        *,
        page_number: int = 1,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[YargitayDecision]:
        """UYAP emsal — Bölge Adliye + Asliye Mahkemesi kararları (keyword-relevance).

        Bedesten'in tarih-sıralı gevşek eşleşmesine karşılık UYAP gerçek keyword
        eşleşmesi yapar; tüketici ayıplı-mal gibi sorgularda alakalı kararları
        (Bölge Adliye Hukuk Daireleri, Asliye Ticaret/Hukuk) döndürür.

        Date filters (DD.MM.YYYY) UYAP'ın "keyword × pencere" pagination'unu açar:
        aynı keyword farklı tarih aralıklarında farklı doc setleri verir, dedup
        cap'ini aşar.
        """
        args: dict[str, Any] = {
            "keyword": keyword,
            "page_number": max(page_number, 1),
        }
        if start_date:
            args["start_date"] = start_date
        if end_date:
            args["end_date"] = end_date
        data = await self._call_tool("search_emsal_detailed_decisions", args)
        items = data.get("decisions") or []
        out: list[YargitayDecision] = []
        for it in items:
            doc_id = str(it.get("id") or "")
            if not doc_id:
                continue
            daire = it.get("daire") or ""
            esas = it.get("esasNo") or ""
            karar = it.get("kararNo") or ""
            title = f"{daire} {esas}/{karar}".strip()
            out.append(
                YargitayDecision(
                    document_id=doc_id,
                    court_type="emsal",
                    chamber=daire or None,
                    title=title or None,
                    date=_normalize_date(it.get("kararTarihi")),
                    summary=it.get("durum"),
                    text="",
                    source_url=(
                        it.get("document_url")
                        or f"https://emsal.uyap.gov.tr/getDokuman?id={doc_id}"
                    ),
                    raw=it,
                )
            )
        return out

    async def get_emsal_document(self, document_id: str) -> str:
        """UYAP emsal tam metni (Markdown)."""
        data = await self._call_tool(
            "get_emsal_document_markdown",
            {"id": document_id},
        )
        return (
            data.get("markdown_content")
            or data.get("content")
            or data.get("markdown")
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

    # ------------------------------------------------------------------
    # Düzenleyici otorite (regulator) arama metotları — Sprint-5 W15
    # ------------------------------------------------------------------

    async def search_kvkk(
        self, keywords: str, page: int = 1
    ) -> list[RegulatorDecision]:
        """KVKK karar arama."""
        data = await self._call_tool(
            "search_kvkk_decisions",
            {"keywords": keywords, "page": max(page, 1)},
        )
        items = _extract_decision_list(data)
        return _parse_regulator_items(items, "kvkk")

    async def search_rekabet(
        self,
        keyword: str | None = None,
        karar_turu: str | None = None,
        page: int = 1,
    ) -> list[RegulatorDecision]:
        """Rekabet Kurumu karar arama."""
        args: dict[str, Any] = {"page": max(page, 1)}
        if keyword:
            args["PdfText"] = keyword
        if karar_turu:
            args["KararTuru"] = karar_turu
        data = await self._call_tool("search_rekabet_kurumu_decisions", args)
        items = _extract_decision_list(data)
        return _parse_regulator_items(items, "rekabet")

    async def search_sayistay(
        self,
        keyword: str,
        decision_type: Literal["genel_kurul", "temyiz_kurulu", "daire"] = "daire",
        page: int = 1,
        length: int = 20,
    ) -> list[RegulatorDecision]:
        """Sayıştay karar arama."""
        args: dict[str, Any] = {
            "decision_type": decision_type,
            "start": (max(page, 1) - 1) * length,
            "length": length,
        }
        if decision_type == "genel_kurul":
            args["karar_tamami"] = keyword
        else:
            args["web_karar_metni"] = keyword
        data = await self._call_tool("search_sayistay_unified", args)
        items = _extract_decision_list(data)
        return _parse_regulator_items(items, "sayistay")

    async def search_bddk(
        self, keywords: str, page: int = 1
    ) -> list[RegulatorDecision]:
        """BDDK karar arama (bankacılık düzenleme)."""
        data = await self._call_tool(
            "search_bddk_decisions",
            {"keywords": keywords, "page": max(page, 1)},
        )
        items = _extract_decision_list(data)
        return _parse_regulator_items(items, "bddk")

    async def search_gib_ozelge(
        self,
        keywords: str | None = None,
        kanun_no: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[RegulatorDecision]:
        """GİB özelge arama (vergi yorumları, 18k+ özelge)."""
        args: dict[str, Any] = {"page": max(page, 1), "pageSize": min(page_size, 50)}
        if keywords:
            args["keywords"] = keywords
        if kanun_no:
            args["kanunNo"] = kanun_no
        data = await self._call_tool("search_gib_ozelge", args)
        items = _extract_decision_list(data)
        return _parse_regulator_items(items, "gib_ozelge")

    async def search_sigorta_tahkim(
        self, keywords: str, page: int = 1
    ) -> list[RegulatorDecision]:
        """Sigorta Tahkim Komisyonu karar arama (trafik/kasko/sağlık)."""
        data = await self._call_tool(
            "search_sigorta_tahkim_decisions",
            {"keywords": keywords, "page": max(page, 1)},
        )
        items = _extract_decision_list(data)
        return _parse_regulator_items(items, "sigorta_tahkim")

    async def get_regulator_document(
        self, regulator: str, doc_ref: str
    ) -> str:
        """Düzenleyici otorite karar metnini Markdown olarak çek."""
        tool_map = {
            "kvkk": ("get_kvkk_document_markdown", "decision_url"),
            "rekabet": ("get_rekabet_kurumu_document", "karar_id"),
            "sayistay": ("get_sayistay_document_unified", "decision_id"),
            "bddk": ("get_bddk_document_markdown", "document_id"),
            "gib_ozelge": ("get_gib_ozelge_document_markdown", "ozelge_id"),
            "sigorta_tahkim": ("get_sigorta_tahkim_document_markdown", "document_id"),
        }
        if regulator not in tool_map:
            raise ValueError(f"Unknown regulator: {regulator}")
        tool_name, key = tool_map[regulator]
        data = await self._call_tool(tool_name, {key: doc_ref})
        return (
            data.get("markdown_content")
            or data.get("markdown_chunk")
            or data.get("markdown")
            or data.get("text")
            or ""
        )


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


def _extract_decision_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Regulator tool yanıtlarındaki karar listesi field'larını generic olarak çıkar."""
    if not isinstance(data, dict):
        return []
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    candidates = (
        data.get("decisions"),
        data.get("results"),
        data.get("items"),
        data.get("ozelgeler"),
        data.get("kararlar"),
        nested.get("decisions") if nested else None,
        nested.get("results") if nested else None,
        nested.get("items") if nested else None,
    )
    for c in candidates:
        if isinstance(c, list) and c:
            return c
    return []


def _parse_regulator_items(
    items: list[dict[str, Any]], regulator: str
) -> list[RegulatorDecision]:
    """Regulator karar listesi → RegulatorDecision[]. Field isimleri kuruma göre değişir."""
    out: list[RegulatorDecision] = []
    for item in items:
        try:
            doc_id = str(
                item.get("decision_id")
                or item.get("document_id")
                or item.get("karar_id")
                or item.get("ozelge_id")
                or item.get("id")
                or item.get("decisionId")
                or item.get("documentId")
                or item.get("kararId")
                or ""
            ).strip()
            if not doc_id:
                continue
            # Sayıştay: title yok; web_karar_konusu + kamu_idaresi_turu birleştir
            title = (
                item.get("title")
                or item.get("baslik")
                or item.get("sayfaAdi")
                or item.get("decision_title")
                or item.get("konu")
                or ""
            )
            if not title and regulator == "sayistay":
                parts = [
                    item.get("web_karar_konusu", ""),
                    item.get("kamu_idaresi_turu", ""),
                ]
                title = " — ".join(p for p in parts if p)
            date_raw = (
                item.get("decision_date")
                or item.get("karar_tarihi")
                or item.get("kararTarihi")
                or item.get("karar_tarih")
                or item.get("YayinlanmaTarihi")
                or item.get("publication_date")
                or item.get("date")
                or item.get("ozelge_tarihi")
            )
            summary = (
                item.get("summary")
                or item.get("ozet")
                or item.get("description")
                or item.get("aciklama")
                or ""
            )
            text = (
                item.get("content")
                or item.get("text")
                or item.get("web_karar_metni")  # sayistay
                or item.get("karar_metni")
                or ""
            )
            url = (
                item.get("source_url")
                or item.get("url")
                or item.get("decision_url")
                or ""
            )
            out.append(
                RegulatorDecision(
                    regulator=regulator,
                    decision_id=doc_id,
                    title=title or None,
                    date=_normalize_date(date_raw if isinstance(date_raw, str) else None),
                    summary=summary or None,
                    text=text,
                    source_url=_normalize_url(url) if isinstance(url, str) else "",
                    raw=item,
                )
            )
        except (ValueError, TypeError) as exc:
            logger.warning("regulator_parse_skipped %s: %s", regulator, exc)
    return out


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
