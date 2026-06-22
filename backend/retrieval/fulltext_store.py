"""İlgili Kararlar tam-metin KALICI cache — SQLite.

`fetch_full_decision` çektiği tam karar metnini buraya yazar; sonraki erişimler (process restart
sonrası, başka kullanıcı dahil) yavaş canlı çekiş yerine ANINDA diskten gelir.

Tasarım kararları:
  - Korpusa/Qdrant'a DOKUNMAZ — ayrı GÖSTERİM katmanı. Retrieval embed'li chunk'larla çalışmaya
    devam eder; bu yalnız tam-metin önbelleği. Embed YOK → retrieval kalitesi etkilenmez.
  - On-demand dolar (24K kararı önden çekme yok). Tıklanan kararlar zamanla hep anında.
  - SQLite (lokal, ağsız, restart-kalıcı). WAL modu → eşzamanlı okuma/yazma güvenli.
  - Async-safe: sqlite3 senkron → tüm DB işi asyncio.to_thread'de (event-loop bloke olmaz).
  - SIFIR HALÜSİNASYON korunur: saklanan metin DOĞRUDAN resmi kaynaktan (yargi-mcp/Firecrawl) gelir,
    model üretmez — cache yalnız o metni tekrar-kullanır.
  - Hata fail-OPEN: DB açılamaz/yazılamazsa "" / None döner → çağıran canlı çekişe düşer (bozulmaz).
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from pathlib import Path

import structlog

log = structlog.get_logger()

# FULLTEXT_CACHE_PATH ile override (testler tmp yol verir). Default backend/data altında (gitignore'lu).
_DEFAULT_PATH = "data/fulltext_cache.sqlite"
# Tek karar metni tavanı (CWE-400 defansif): dev/bozuk metin DB'yi şişirmesin. Gerçek karar << 2MB.
_MAX_TEXT_BYTES = 2_000_000
_MIN_TEXT_CHARS = 40  # full_decision._is_real_text ile tutarlı: çöp/boş yazma
# Toplam satır tavanı (CWE-400): sınırsız disk büyümesini engelle. Aşınca en eski fetched_at'ler
# budanır (LRU). Korpusta ~24.5K benzersiz karar var → 50K bol headroom. ENV ile ayarlanır.
_MAX_ROWS = int(os.getenv("FULLTEXT_CACHE_MAX_ROWS", "50000"))


def _db_path() -> Path:
    p = Path(os.getenv("FULLTEXT_CACHE_PATH", _DEFAULT_PATH))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fulltext ("
        "  key TEXT PRIMARY KEY,"
        "  text TEXT NOT NULL,"
        "  fetched_at REAL NOT NULL"
        ")",
    )
    return conn


def _get_sync(key: str) -> str | None:
    if not key:
        return None
    try:
        with _connect() as conn:
            row = conn.execute("SELECT text FROM fulltext WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None
    except Exception as exc:  # DB kilidi/bozulma → fail-open (canlı çekişe düş)
        log.warning("fulltext_cache_get_failed", error=type(exc).__name__)
        return None


def _put_sync(key: str, text: str) -> None:
    if not key or not text or len(text) < _MIN_TEXT_CHARS:
        return
    if len(text.encode("utf-8", "ignore")) > _MAX_TEXT_BYTES:
        log.warning("fulltext_cache_skip_oversize", key_len=len(key))
        return
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fulltext(key, text, fetched_at) VALUES (?, ?, ?)",
                (key, text, time.time()),
            )
            # LRU budama: tavanı aşınca en eski fetched_at'leri sil (sınırsız disk büyümesi guard).
            # Aynı INSERT işlemiyle atomik. fetched_at zaten yazıldığı için budama ucuz.
            n = conn.execute("SELECT COUNT(*) FROM fulltext").fetchone()[0]
            if n > _MAX_ROWS:
                conn.execute(
                    "DELETE FROM fulltext WHERE key IN "
                    "(SELECT key FROM fulltext ORDER BY fetched_at ASC LIMIT ?)",
                    (n - _MAX_ROWS,),
                )
    except Exception as exc:  # yazma hatası ASLA ana akışı bozmasın
        log.warning("fulltext_cache_put_failed", error=type(exc).__name__)


async def get(key: str) -> str | None:
    """Kalıcı cache'ten tam metni oku (yoksa/hata → None). Event-loop bloke olmaz."""
    return await asyncio.to_thread(_get_sync, key)


async def put(key: str, text: str) -> None:
    """Tam metni kalıcı cache'e yaz (idempotent; çöp/devasa atlanır). Event-loop bloke olmaz."""
    await asyncio.to_thread(_put_sync, key, text)


def stats() -> dict:
    """Cache istatistiği (gözlemlenebilirlik/health): kayıt sayısı + yol."""
    try:
        with _connect() as conn:
            n = conn.execute("SELECT COUNT(*) FROM fulltext").fetchone()[0]
        return {"count": int(n), "path": str(_db_path())}
    except Exception as exc:
        return {"count": -1, "error": type(exc).__name__}


__all__ = ("get", "put", "stats")
