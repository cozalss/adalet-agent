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
# Single-flight: aynı karar için UÇUŞTAKİ canlı çekiş (key → Task). Otomatik-yükle (panel)
# + tıklama + paralel istekler aynı kararı çekerse TEK isteğe indirir (public mcp'ye nazik).
_inflight: dict[str, object] = {}
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


async def _fetch_yargi_text(
    source_url: str, source_id: str, court: str, timeout_s: float,
) -> tuple[str, str | None]:
    """yargi-mcp'den tam metni çek (yerel→public fallback + rate-limit backoff). → (text, base_error).

    base_error: None (text gerçek) | 'timeout' | 'rate_limited' | 'not_found' | hata-tipi.
    """
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

    try:
        text = await asyncio.wait_for(_do(), timeout=timeout_s)
    except TimeoutError:
        log.warning("full_decision_timeout", source_id=source_id)
        return "", "timeout"
    except httpx.HTTPStatusError as exc:  # 429 → rate_limited (jenerik değil net mesaj)
        code = exc.response.status_code
        log.warning("full_decision_http_error", status=code)
        return "", ("rate_limited" if code == 429 else "not_found")
    except Exception as exc:
        log.warning("full_decision_failed", error=str(exc) or type(exc).__name__)
        return "", type(exc).__name__

    if _looks_rate_limited(text):
        return "", "rate_limited"
    if not _is_real_text(text):
        return "", "not_found"
    return text, None


async def _firecrawl_fallback(source_url: str, source_id: str, timeout_s: float) -> str:
    """yargi-mcp getiremeyince Firecrawl ile bilinen hukuki URL'den temiz metin (yedek).

    Anahtar yok / host izinli değil / hata → "" (çağıran orijinal hatayı döndürür). Yedek ASLA
    ana akışı bozmaz. Sıfır halüsinasyon: içerik doğrudan resmi sayfadan (model üretmez)."""
    from retrieval.firecrawl_client import scrape_legal_url
    try:
        text = await scrape_legal_url(source_url, timeout_s=min(timeout_s, 30.0))
    except Exception as exc:
        log.warning("firecrawl_fallback_error", error=type(exc).__name__)
        return ""
    if text:
        log.info("full_decision_firecrawl_fallback", source_id=source_id)
    return text


def _normalized_cache_key(source_url: str, source_id: str) -> str:
    """Kararı tekil tanımlayan KARARLI cache key — aynı kararın farklı URL/param varyasyonları TEK
    key olur (kardinalite kaynakta sınırlanır + collision yüzeyi kapanır). Bedesten/Yargıtay/Danıştay
    documentId (en yaygın) → host:id; çıkarılamazsa ham source_url|source_id fallback (CWE-524 sınırlı).
    Host öneki cross-kaynak rakam çakışmasını önler. in-process + disk cache AYNI key'i kullanır."""
    doc_id = bedesten_document_id(source_url, source_id)
    if doc_id:
        return f"{_hostname(source_url) or 'doc'}:{doc_id}"
    return f"{(source_url or '')[:512]}|{(source_id or '')[:128]}"


async def fetch_full_decision(
    source_url: str, source_id: str = "", court: str = "", *, timeout_s: float = 45.0,
) -> dict:
    """Kararın TAM metnini çek. → {'text': str, 'cached': bool, 'error': str|None}.

    error kodları: None (başarı) | 'not_found' | 'rate_limited' | 'timeout' | hata-tipi.
    """
    # Kararlı, normalize key (kardinalite + collision guard; CWE-524 boyut sınırı fallback'te korunur).
    key = _normalized_cache_key(source_url, source_id)
    if key in _cache:
        return {"text": _cache[key], "cached": True, "error": None}

    # KALICI cache (disk) — restart sonrası / başka kullanıcı için ANINDA (yavaş canlı çekiş yok).
    # Korpusa dokunmaz; yalnız daha önce çekilmiş tam metni tekrar-kullanır. Hata → None (fail-open).
    from retrieval import fulltext_store
    persisted = await fulltext_store.get(key)
    if persisted:
        _cache_put(key, persisted)
        return {"text": persisted, "cached": True, "error": None}

    # SINGLE-FLIGHT: aynı karar UÇUŞTA ise mevcut isteği paylaş (çift canlı-çekiş yok → rate-limit
    # dostu; özellikle panel 5 kararı otomatik-yüklerken + kullanıcı tıklarken kritik).
    existing = _inflight.get(key)
    if existing is not None:
        return await existing  # type: ignore[no-any-return]
    import asyncio
    task = asyncio.ensure_future(
        _live_fetch_and_cache(key, source_url, source_id, court, timeout_s),
    )
    _inflight[key] = task
    try:
        return await task
    finally:
        _inflight.pop(key, None)


async def _live_fetch_and_cache(
    key: str, source_url: str, source_id: str, court: str, timeout_s: float,
) -> dict:
    """yargi-mcp → Firecrawl yedeği canlı çekiş; başarıda in-process + kalıcı cache'e yaz."""
    from retrieval import fulltext_store
    text, base_error = await _fetch_yargi_text(source_url, source_id, court, timeout_s)
    if base_error is None:
        _cache_put(key, text)
        await fulltext_store.put(key, text)  # bir daha çekme: kalıcı kaydet
        return {"text": text, "cached": False, "error": None}

    # yargi-mcp getiremedi (hata/boş/rate-limited) → Firecrawl YEDEĞİ (bilinen hukuki URL).
    fc_text = await _firecrawl_fallback(source_url, source_id, timeout_s)
    if _is_real_text(fc_text):
        _cache_put(key, fc_text)
        await fulltext_store.put(key, fc_text)  # bir daha çekme: kalıcı kaydet
        return {"text": fc_text, "cached": False, "error": None}

    return {"text": "", "cached": False, "error": base_error}


__all__ = ("bedesten_document_id", "fetch_full_decision")
