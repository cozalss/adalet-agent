"""yargi-mcp HTTP istemcisi — Yargıtay + Danıştay açık veri erişimi.

yargi-mcp: https://github.com/saidsurucu/yargi-mcp
Lokal MCP sunucusu olarak çalışır (varsayılan port 5001). Bu modül HTTP REST
sarmalayıcısı sunar; gerçek endpoint isimleri yargi-mcp dokümantasyonuna göre
doldurulmalıdır.

NOT: yargi-mcp MCP/JSON-RPC kullanıyor olabilir — eğer durum buysa, bu modül
HTTP REST adapter olarak kullanılır ve yargi-mcp'nin REST gateway'i devreye
alınmalıdır. Detay: yargi-mcp README.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = structlog.get_logger()

YARGI_MCP_URL = os.getenv("YARGI_MCP_URL", "http://localhost:5001")
YARGI_MCP_TIMEOUT_MS = int(os.getenv("YARGI_MCP_TIMEOUT_MS", "15000"))


@dataclass(slots=True)
class YargitayDecision:
    """Tek bir Yargıtay kararı (chunklamadan önce ham hâli)."""

    id: str
    court: str
    chamber: str | None
    esas_no: str | None
    karar_no: str | None
    date: str | None
    keywords: list[str]
    summary: str | None
    text: str
    source_url: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "doc_id": self.id,
            "court": self.court,
            "chamber": self.chamber,
            "esas_no": self.esas_no,
            "karar_no": self.karar_no,
            "date": self.date,
            "keywords": self.keywords,
            "source": "yargitay",
            "source_url": self.source_url,
        }


class YargiClient:
    """yargi-mcp HTTP client. Async kullanım için `async with`."""

    def __init__(
        self,
        base_url: str = YARGI_MCP_URL,
        timeout_ms: int = YARGI_MCP_TIMEOUT_MS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout_ms / 1000.0
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> YargiClient:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self._timeout,
            headers={"User-Agent": "adalet-agent/0.1"},
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def search_yargitay(
        self,
        keyword: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[YargitayDecision]:
        """Yargıtay kararları anahtar kelime arama."""
        assert self._client is not None, "Use 'async with YargiClient(...)'"
        # TODO: yargi-mcp gerçek endpoint adıyla güncelle.
        # MCP-style ise tools/call → search_yargitay_detailed gibi olabilir.
        resp = await self._client.get(
            "/api/yargitay/search",
            params={"keyword": keyword, "limit": limit, "offset": offset},
        )
        resp.raise_for_status()
        items = resp.json()
        return [_parse_decision(item) for item in items]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def get_decision(self, decision_id: str) -> YargitayDecision | None:
        """Tek bir karar — tam metin için."""
        assert self._client is not None
        # TODO: yargi-mcp endpoint adıyla güncelle.
        resp = await self._client.get(f"/api/yargitay/decision/{decision_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_decision(resp.json())

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def health(self) -> bool:
        assert self._client is not None
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False


def _parse_decision(item: dict[str, Any]) -> YargitayDecision:
    """yargi-mcp ham JSON → YargitayDecision."""
    return YargitayDecision(
        id=str(item.get("id") or item.get("decision_id") or ""),
        court=item.get("court", "Yargıtay"),
        chamber=item.get("chamber") or item.get("daire"),
        esas_no=item.get("esas_no") or item.get("esasNo"),
        karar_no=item.get("karar_no") or item.get("kararNo"),
        date=item.get("date") or item.get("karar_tarihi"),
        keywords=item.get("keywords") or [],
        summary=item.get("summary") or item.get("ozet"),
        text=item.get("content") or item.get("metin") or item.get("text") or "",
        source_url=item.get("url") or item.get("source_url") or "",
    )
