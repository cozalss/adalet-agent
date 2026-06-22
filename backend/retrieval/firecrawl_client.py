"""Firecrawl ile bilinen hukuki URL'den temiz markdown çek — yargi-mcp tam-metin YEDEĞİ.

Kök ihtiyaç: `fetch_full_decision` kararın tam metnini yargi-mcp'den çeker; yerel+public mcp
de getiremezse (not_found/rate_limited) kullanıcı boş panel görür. Firecrawl, kararın/mevzuatın
BİLİNEN resmi URL'sinden sayfanın temiz markdown'ını çekerek bu boşluğu doldurur.

Tasarım (ADALET desenleri):
  - Raw httpx async (openai_compat/yargi_client deseni — SDK YOK, event-loop'u bloke etmez).
  - Anahtar `.env`'den (FIRECRAWL_API_KEY); ASLA hardcode. Anahtar yoksa no-op ("") → yedek atlanır.
  - SSRF/abuse + maliyet guard: YALNIZ resmi hukuki host allowlist'i çekilir (gelişigüzel URL değil).
  - SIFIR HALÜSİNASYON: içerik DOĞRUDAN resmi sayfadan; model üretmez (yargi-mcp ile aynı garanti).
  - Hata/anahtarsız/izinsiz → "" döner; çağıran dürüstçe "getirilemedi" der (graceful).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx
import structlog

log = structlog.get_logger()

_BASE_URL = "https://api.firecrawl.dev/v2"
_SCRAPE_PATH = "/scrape"

# Yalnız resmi/güvenilir hukuki kaynaklar — Firecrawl'a gelişigüzel URL çektirme (maliyet/abuse +
# legal-only sıfır-halüsinasyon ilkesi). Host TAM-EŞLEŞME (substring spoof'lanır; full_decision deseni).
_ALLOWED_HOSTS: frozenset[str] = frozenset({
    "mevzuat.gov.tr", "www.mevzuat.gov.tr",
    "anayasa.gov.tr", "www.anayasa.gov.tr", "kararlarbilgibankasi.anayasa.gov.tr",
    "emsal.uyap.gov.tr",
    "karararama.yargitay.gov.tr", "www.yargitay.gov.tr", "yargitay.gov.tr",
    "danistay.gov.tr", "www.danistay.gov.tr",
    "resmigazete.gov.tr", "www.resmigazete.gov.tr",
})

_MIN_REAL_CHARS = 40  # full_decision._is_real_text ile tutarlı: çok kısa = anlamlı metin değil


def firecrawl_enabled() -> bool:
    """FIRECRAWL_API_KEY set mi? (yedek devreye girsin mi kararı)."""
    return bool(os.getenv("FIRECRAWL_API_KEY", "").strip())


def host_allowed(url: str) -> bool:
    """URL'in host'u resmi hukuki allowlist'te mi? (SSRF/abuse + legal-only)."""
    try:
        return (urlparse(url or "").hostname or "").lower() in _ALLOWED_HOSTS
    except ValueError:
        return False


async def scrape_legal_url(url: str, *, timeout_s: float = 30.0) -> str:
    """Bilinen hukuki URL → temiz markdown (yedek). Anahtar yok / host izinli değil / hata → "".

    Çağıran (fetch_full_decision) "" görünce yedeği bırakıp orijinal hatayı döndürür.
    """
    key = os.getenv("FIRECRAWL_API_KEY", "").strip()
    if not key:
        return ""
    if not host_allowed(url):
        log.info("firecrawl_skip_host_not_allowed", host=urlparse(url or "").hostname or "")
        return ""

    payload = {"url": url, "formats": ["markdown"], "onlyMainContent": True}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        # follow_redirects=False: SSRF redirect-bypass sertleştirme (openai_compat/yargi_client deseni).
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
            resp = await client.post(f"{_BASE_URL}{_SCRAPE_PATH}", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning("firecrawl_scrape_failed", error=type(exc).__name__)
        return ""

    # v2 yanıt şekli: {"success": true, "data": {"markdown": "...", ...}}
    md = ((data.get("data") or {}).get("markdown") or "").strip()
    if len(md) < _MIN_REAL_CHARS:
        return ""
    log.info("firecrawl_scrape_done", host=urlparse(url).hostname or "", n_chars=len(md))
    return md


_SEARCH_PATH = "/search"


async def search_mevzuat_url(query: str, *, timeout_s: float = 40.0) -> str:
    """Firecrawl search ile resmi mevzuat.gov.tr URL'i bul (yönetmelik/kanun seed için).

    Sorguya en uygun `www.mevzuat.gov.tr/mevzuat?MevzuatNo=...` sonucunu döndürür (host allowlist'li);
    bulamazsa "". MevzuatNo'yu elle bilmeye gerek kalmaz. Anahtar yok/hata → "".
    """
    key = os.getenv("FIRECRAWL_API_KEY", "").strip()
    if not key:
        return ""
    payload = {"query": query, "limit": 6}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
            resp = await client.post(f"{_BASE_URL}{_SEARCH_PATH}", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning("firecrawl_search_failed", error=type(exc).__name__)
        return ""

    raw = data.get("data") or {}
    results = raw.get("web") if isinstance(raw, dict) else raw
    for item in results or []:
        url = (item or {}).get("url", "")
        if host_allowed(url) and "mevzuat.gov.tr/mevzuat" in url:
            log.info("firecrawl_search_hit", url=url[:90])
            return url
    return ""


__all__ = ("firecrawl_enabled", "host_allowed", "scrape_legal_url", "search_mevzuat_url")
