"""Bir kararın TAM metnini yargi-mcp'den on-demand çek (İlgili Kararlar paneli için).

Kök ihtiyaç: korpus kararları PARÇALI indeksliyor (karar başına ort. 1.2 dağınık chunk;
tam metin yok). Kullanıcı "tam metni" isteyince Bedesten/UYAP/Anayasa'dan kararın TAMAMINI
canlı çekeriz. Kimlik korpus payload'ından: `source_url` (karararama ?aranan=<documentId>)
veya `source_id` (chunk_id "h-525485900-c14" → documentId 525485900). Fizibilite doğrulandı:
get_document(525485900) → tam içtihat metni (3700+ karakter).

Sıfır halüsinasyon: metin DOĞRUDAN resmi kaynaktan (yargi-mcp), model üretmez. Ağ/parse/
rate-limit hatasında boş + error → çağıran dürüstçe "getirilemedi" der. Statik kararlar →
in-process cache (rate-limit dostu). Cache decision-id bazlı, boyut-sınırlı.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

import httpx
import structlog

log = structlog.get_logger()

_cache: dict[str, str] = {}
_CACHE_MAX = 256
_RATE_LIMIT_RETRY_DELAY_S = 2.0
# Paylaşımlı public mcp eşzamanlılık/rate sınırı yiyebiliyor (yerel mcp kapalıyken her
# istek public'e düşer) → birkaç kez backoff'lu yeniden dene; çoğu geçici sınır düzelir.
_RATE_LIMIT_MAX_TRIES = 3
# Yapılandırılmış mcp (genelde yerel YARGI_MCP_URL=127.0.0.1:8765) erişilemezse
# resmi public instance'a düş → yerel mcp kapalı olsa da tam-metin çalışır.
_PUBLIC_YARGI_MCP = "https://yargimcp.surucu.dev/mcp"


def _is_connection_error(exc: Exception) -> bool:
    """Bağlantı kurulamadı mı? (yerel mcp kapalı → public'e düşmek için). DAR: yalnız
    transport/bağlantı hataları — ham OSError (PermissionError/FileNotFound) gerçek bir
    bug'ı maskelememeli (ECC). httpx.ConnectError TransportError altsınıfıdır."""
    return isinstance(exc, (httpx.TransportError, ConnectionError))


def _hostname(url: str) -> str:
    """URL'in host'unu güvenle çıkar (SSRF allowlist için — substring kontrolü spoof'lanır)."""
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def bedesten_document_id(source_url: str, source_id: str = "") -> str:
    """Bedesten documentId'yi çıkar. Öncelik: source_url'deki `aranan=<id>`; yoksa
    chunk_id kökünden ("h-525485900-c14" → "525485900"). Bulunamazsa "".
    """
    m = re.search(r"aranan=(\d+)", source_url or "")
    if m:
        return m.group(1)
    base = re.sub(r"[-_]c?\d+$", "", (source_id or "").strip())  # "-c14" chunk son-ekini at
    m2 = re.search(r"(\d{5,})", base)
    return m2.group(1) if m2 else ""


def _looks_rate_limited(text: str) -> bool:
    """yargi-mcp rate-limit'i markdown İÇERİĞİ olarak döndürebiliyor (gerçek metin değil).
    SADECE kesin imza 'rate_limit_exceeded' aranır — eski 'error (' başlangıcı gerçek karar
    metnini yanlış-pozitif yapabiliyordu (ECC)."""
    return "rate_limit_exceeded" in (text or "")[:200].lower()


def _is_real_text(text: str) -> bool:
    return bool(text) and not _looks_rate_limited(text) and len(text.strip()) >= 40


def _cache_put(key: str, text: str) -> None:
    if key in _cache:
        return
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))  # FIFO en eskiyi at
    _cache[key] = text


async def _route_fetch(yc, source_url: str, source_id: str, court: str) -> str:
    """Kaynak türüne göre doğru yargi-mcp tam-metin metodunu çağır.

    SSRF koruması: source_url DOĞRUDAN fetch edilmez. Host TAM-EŞLEŞME allowlist ile
    doğrulanır (substring 'evil.com/anayasa.gov.tr' ile spoof'lanırdı — ECC HIGH). Bedesten
    yalnız çıkarılan RAKAM documentId'yi; UYAP yalnız RAKAM id'yi; Anayasa yalnız resmi
    host'tan çeker. Eşleşme yoksa boş."""
    host = _hostname(source_url)
    if host == "emsal.uyap.gov.tr":
        m = re.search(r"id=(\d+)", source_url or "")  # yalnız rakam id (ECC MEDIUM)
        return await yc.get_emsal_document(m.group(1)) if m else ""
    if host in {"anayasa.gov.tr", "www.anayasa.gov.tr", "kararlarbilgibankasi.anayasa.gov.tr"}:
        return await yc.get_anayasa_document(source_url)
    # Varsayılan: Bedesten (Yargıtay/Danıştay) — yalnız documentId (rakam) ile tam Markdown.
    doc_id = bedesten_document_id(source_url, source_id)
    return await yc.get_document(doc_id) if doc_id else ""


async def fetch_full_decision(
    source_url: str, source_id: str = "", court: str = "", *, timeout_s: float = 45.0,
) -> dict:
    """Kararın TAM metnini çek. → {'text': str, 'cached': bool, 'error': str|None}.

    error kodları: None (başarı) | 'not_found' | 'rate_limited' | 'timeout' | hata-tipi.
    """
    key = f"{source_url or ''}|{source_id or ''}"
    if key in _cache:
        return {"text": _cache[key], "cached": True, "error": None}

    try:
        from retrieval.yargi_client import YargiClient

        async def _attempt(base_url: str | None) -> str:
            kwargs = {"base_url": base_url} if base_url else {}
            async with YargiClient(**kwargs) as yc:
                text = ""
                # Rate-limit (içerik VEYA HTTP 429) → artan backoff ile birkaç kez dene.
                for i in range(_RATE_LIMIT_MAX_TRIES):
                    try:
                        text = await _route_fetch(yc, source_url, source_id, court)
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code == 429 and i < _RATE_LIMIT_MAX_TRIES - 1:
                            await asyncio.sleep(_RATE_LIMIT_RETRY_DELAY_S * (i + 1))
                            continue
                        raise
                    if not _looks_rate_limited(text) or i == _RATE_LIMIT_MAX_TRIES - 1:
                        return text
                    await asyncio.sleep(_RATE_LIMIT_RETRY_DELAY_S * (i + 1))  # 2s, 4s
                return text

        async def _do() -> str:
            try:
                return await _attempt(None)  # yapılandırılmış (genelde yerel) mcp
            except Exception as exc:
                if _is_connection_error(exc):  # yerel mcp kapalı → resmi public'e düş
                    log.info("full_decision_public_fallback", error=type(exc).__name__)
                    return await _attempt(_PUBLIC_YARGI_MCP)
                raise

        text = await asyncio.wait_for(_do(), timeout=timeout_s)
    except TimeoutError:
        log.warning("full_decision_timeout", source_id=source_id)
        return {"text": "", "cached": False, "error": "timeout"}
    except httpx.HTTPStatusError as exc:  # 429 → rate_limited (jenerik değil net mesaj)
        code = exc.response.status_code
        log.warning("full_decision_http_error", status=code)
        return {"text": "", "cached": False, "error": "rate_limited" if code == 429 else "not_found"}
    except Exception as exc:
        log.warning("full_decision_failed", error=str(exc) or type(exc).__name__)
        return {"text": "", "cached": False, "error": type(exc).__name__}

    if _looks_rate_limited(text):
        return {"text": "", "cached": False, "error": "rate_limited"}
    if not _is_real_text(text):
        return {"text": "", "cached": False, "error": "not_found"}

    _cache_put(key, text)
    return {"text": text, "cached": False, "error": None}


__all__ = ("bedesten_document_id", "fetch_full_decision")
