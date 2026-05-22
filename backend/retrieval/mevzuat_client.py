"""mevzuat.gov.tr scraper — Türk hukukunun resmi mevzuat kaynağı.

Strateji:
- yargi-mcp birçok mevzuat erişimi sunuyorsa onu tercih et (önce dene)
- yoksa mevzuat.gov.tr'nin HTML sayfalarını parse et (BeautifulSoup)
- Etik kazıma: robots.txt'e saygı, rate limit, kullanıcı ajanı

Kanun kodları:
- TBK: 6098 sayılı Türk Borçlar Kanunu (kira)
- IK:  4857 sayılı İş Kanunu
- TKHK: 6502 sayılı Tüketicinin Korunması Hakkında Kanun
- SGK: 5510 sayılı Sosyal Sigortalar ve Genel Sağlık Sigortası Kanunu
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = structlog.get_logger()

MEVZUAT_BASE_URL = os.getenv("MEVZUAT_URL", "https://www.mevzuat.gov.tr")
DEFAULT_DELAY_SEC = float(os.getenv("MEVZUAT_DELAY_SEC", "1.0"))

KANUN_KODU_TO_NUMARA = {
    "TBK": "6098",
    "IK": "4857",
    "TKHK": "6502",
    "SGK": "5510",
}


@dataclass(slots=True)
class Madde:
    """Tek bir kanun maddesi."""

    kanun_kodu: str
    kanun_numarasi: str
    kanun_adi: str
    madde_no: int
    baslik: str | None
    metin: str
    source_url: str

    @property
    def id(self) -> str:
        return f"m-{self.kanun_kodu}-{self.madde_no}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "doc_id": self.id,
            "kanun_kodu": self.kanun_kodu,
            "kanun_numarasi": self.kanun_numarasi,
            "kanun_adi": self.kanun_adi,
            "madde_no": self.madde_no,
            "baslik": self.baslik,
            "source": "mevzuat",
            "source_url": self.source_url,
        }


class MevzuatClient:
    """mevzuat.gov.tr scraper. Async kullanım için `async with`."""

    def __init__(
        self,
        base_url: str = MEVZUAT_BASE_URL,
        delay_sec: float = DEFAULT_DELAY_SEC,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.delay_sec = delay_sec
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> MevzuatClient:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            headers={
                "User-Agent": "adalet-agent/0.1 (academic research)",
                "Accept-Language": "tr-TR,tr;q=0.9",
            },
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_kanun(self, kanun_kodu: str) -> list[Madde]:
        """Bir kanunun tüm maddelerini çek."""
        numara = KANUN_KODU_TO_NUMARA.get(kanun_kodu)
        if not numara:
            raise ValueError(f"Bilinmeyen kanun kodu: {kanun_kodu}")

        log.info("kanun_fetch_started", kod=kanun_kodu, numara=numara)
        html = await self._fetch_kanun_html(numara)
        maddeler = _parse_kanun_html(
            html,
            kanun_kodu=kanun_kodu,
            kanun_numarasi=numara,
            source_url=self._kanun_url(numara),
        )
        log.info("kanun_fetch_completed", kod=kanun_kodu, madde_count=len(maddeler))
        return maddeler

    async def fetch_madde(self, kanun_kodu: str, madde_no: int) -> Madde | None:
        """Tek bir maddeyi çek — citation verification için kritik.

        Doğrulama sürecinde her referans için canlı kaynaktan fetch edilir.
        """
        maddeler = await self.fetch_kanun(kanun_kodu)
        for madde in maddeler:
            if madde.madde_no == madde_no:
                return madde
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch_kanun_html(self, numara: str) -> str:
        assert self._client is not None
        url = self._kanun_url(numara)
        resp = await self._client.get(url)
        resp.raise_for_status()
        await asyncio.sleep(self.delay_sec)
        return resp.text

    def _kanun_url(self, numara: str) -> str:
        # NOT: mevzuat.gov.tr URL pattern'i zaman zaman değişir.
        # Doğrulanan endpoint çalıştırma sırasında test edilmelidir.
        return f"/mevzuatmetin/1.5.{numara}.pdf"


def _parse_kanun_html(
    html: str,
    *,
    kanun_kodu: str,
    kanun_numarasi: str,
    source_url: str,
) -> list[Madde]:
    """HTML kanun sayfasından madde madde parse et.

    NOT: mevzuat.gov.tr PDF ve HTML her ikisini de sunar. HTML versiyonu varsa
    bu fonksiyon yeterlidir; PDF'ten extract için pdfplumber gerekir
    (gelecekte eklenecek).
    """
    soup = BeautifulSoup(html, "html.parser")
    kanun_adi = _extract_kanun_adi(soup) or kanun_kodu

    maddeler: list[Madde] = []
    for el in soup.select("div.madde, p.madde, .MaddeBaslik"):
        text = el.get_text("\n", strip=True)
        if not text or not text.lower().startswith("madde"):
            continue

        madde_no = _extract_madde_no(text)
        if madde_no is None:
            continue

        maddeler.append(
            Madde(
                kanun_kodu=kanun_kodu,
                kanun_numarasi=kanun_numarasi,
                kanun_adi=kanun_adi,
                madde_no=madde_no,
                baslik=_extract_baslik(text),
                metin=text,
                source_url=source_url,
            )
        )

    return maddeler


def _extract_kanun_adi(soup: BeautifulSoup) -> str | None:
    title = soup.find("title")
    return title.get_text(strip=True) if title else None


def _extract_madde_no(text: str) -> int | None:
    import re

    m = re.search(r"Madde\s+(\d+)", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_baslik(text: str) -> str | None:
    """Madde başlığı genelde madde numarasından sonra gelir."""
    import re

    m = re.search(r"Madde\s+\d+\s*[\.\-—]\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None
