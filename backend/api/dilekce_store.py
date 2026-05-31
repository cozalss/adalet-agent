"""Dilekçe PDF in-memory cache — TTL + LRU bounded.

MVP (Sprint-7/8): in-process dict; production'da MinIO presigned URL ile
aynı interface'i taşıyabilir.

Güvenlik:
    - **owner_sub**: PDF'i sadece üreten principal indirebilir (IDOR koruması)
    - **Bounded**: `max_entries=200` LRU; sınırsız bellek tüketimi engellenir
    - **TTL**: 15 dk; expired girdiler `get()` ve `store()` sırasında temizlenir

KVKK:
    - Disk persistence YOK
    - `DELETE /api/dilekce/{cid}` ile veri sahibi silme hakkı kullanır
    - Template/içerik log'larda yer almaz (yalnız boyut + cid)
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

import structlog

from agents.config import DILEKCE_CACHE_TTL_S

log = structlog.get_logger()

# LRU cache üst sınırı — 200 × ~5MB = 1GB worst case. Process RAM bütçesi
# içinde rahat sığar. ENV ile override edilebilir (test'te küçültülür).
_MAX_ENTRIES = int(os.getenv("DILEKCE_CACHE_MAX_ENTRIES", "200"))
# Yüksek-su işareti: log warn eşiği (capacity %75)
_HIGH_WATERMARK = int(_MAX_ENTRIES * 0.75)


@dataclass(frozen=True)
class _Entry:
    """TTL-tagged PDF (+ opsiyonel DOCX) cache record + ownership audit."""

    pdf_bytes: bytes
    filename: str
    template_id: str
    owner_sub: str          # principal.sub — IDOR koruması
    expires_at: float
    docx_bytes: bytes | None = None  # editlenebilir Word çıktısı (varsa)
    docx_filename: str = ""


class _DilekceCache:
    """Thread-safe TTL+LRU cache. Singleton (process-wide)."""

    def __init__(
        self, ttl_s: int = DILEKCE_CACHE_TTL_S, max_entries: int = _MAX_ENTRIES,
    ) -> None:
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._data: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()

    def store(
        self, conversation_id: str, pdf_bytes: bytes,
        filename: str, template_id: str, owner_sub: str,
        docx_bytes: bytes | None = None, docx_filename: str = "",
    ) -> None:
        """conversation_id → PDF (+ opsiyonel DOCX) + owner. LRU eviction max_entries'te."""
        if not conversation_id:
            return
        expires = time.time() + self._ttl_s
        entry = _Entry(
            pdf_bytes=pdf_bytes, filename=filename,
            template_id=template_id, owner_sub=owner_sub or "",
            expires_at=expires,
            docx_bytes=docx_bytes, docx_filename=docx_filename,
        )
        with self._lock:
            self._data.pop(conversation_id, None)  # mevcudu sona taşı (LRU)
            self._data[conversation_id] = entry
            self._gc_expired_locked()
            self._evict_lru_locked()
            n_cached = len(self._data)
        if n_cached >= _HIGH_WATERMARK:
            log.warning(
                "dilekce_cache_high_watermark",
                n_cached=n_cached, max_entries=self._max_entries,
            )
        log.info(
            "dilekce_cache_store",
            cid=conversation_id, pdf_bytes=len(pdf_bytes), n_cached=n_cached,
        )

    def get(self, conversation_id: str) -> _Entry | None:
        """Süresi dolmuşsa None döner ve siler. LRU recency güncellenmez
        (read-only erişim eviction'a etki etmez — kasıtlı sadelik)."""
        if not conversation_id:
            return None
        now = time.time()
        with self._lock:
            entry = self._data.get(conversation_id)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._data.pop(conversation_id, None)
                return None
            return entry

    def delete(self, conversation_id: str) -> bool:
        """Veri sahibi silme hakkı (KVKK m.7) — kayıt varsa siler, True döner."""
        with self._lock:
            removed = self._data.pop(conversation_id, None) is not None
        if removed:
            log.info("dilekce_cache_deleted", cid=conversation_id)
        return removed

    def _gc_expired_locked(self) -> None:
        now = time.time()
        expired = [k for k, e in self._data.items() if e.expires_at <= now]
        for k in expired:
            self._data.pop(k, None)

    def _evict_lru_locked(self) -> None:
        while len(self._data) > self._max_entries:
            evicted_key, _ = self._data.popitem(last=False)
            log.info("dilekce_cache_evict_lru", cid=evicted_key)

    def clear(self) -> None:
        """Test fixture — cache'i sıfırla."""
        with self._lock:
            self._data.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._data)


# Process-wide singleton (lifespan boyunca yaşar; restart silebilir).
_cache = _DilekceCache()


def store_pdf(
    conversation_id: str, pdf_bytes: bytes,
    filename: str, template_id: str, owner_sub: str,
    docx_bytes: bytes | None = None, docx_filename: str = "",
) -> None:
    _cache.store(conversation_id, pdf_bytes, filename, template_id, owner_sub,
                 docx_bytes=docx_bytes, docx_filename=docx_filename)


def get_pdf(conversation_id: str) -> _Entry | None:
    return _cache.get(conversation_id)


def delete_pdf(conversation_id: str) -> bool:
    return _cache.delete(conversation_id)


def clear_cache() -> None:
    _cache.clear()


def cache_size() -> int:
    return _cache.size


__all__ = ("cache_size", "clear_cache", "delete_pdf", "get_pdf", "store_pdf")
