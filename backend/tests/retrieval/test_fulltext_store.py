"""İlgili Kararlar tam-metin KALICI cache — store round-trip + fetch_full_decision entegrasyonu.
conftest `_isolate_fulltext_cache` her teste ayrı tmp SQLite verir (gerçek cache kirlenmez)."""
from __future__ import annotations

import asyncio

import pytest

import retrieval.full_decision as fd
import retrieval.fulltext_store as fts

_LONG = "Kararın tam metni yeterince uzun olsun burada. " * 3


@pytest.mark.asyncio
async def test_put_get_roundtrip():
    await fts.put("k1", _LONG)
    out = await fts.get("k1")
    assert out is not None and "tam metni" in out


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    assert await fts.get("yok-boyle-bir-key") is None
    assert await fts.get("") is None


@pytest.mark.asyncio
async def test_put_skips_empty_short_oversize(monkeypatch):
    await fts.put("bos", "")
    await fts.put("kisa", "kısa")  # < _MIN_TEXT_CHARS
    monkeypatch.setattr(fts, "_MAX_TEXT_BYTES", 50)
    await fts.put("buyuk", "x" * 200)  # > tavan
    assert await fts.get("bos") is None
    assert await fts.get("kisa") is None
    assert await fts.get("buyuk") is None


@pytest.mark.asyncio
async def test_persists_across_connections():
    # Her put/get yeni connection açar → SQLite diske yazar (restart-kalıcı simülasyonu)
    await fts.put("kal", _LONG)
    assert await fts.get("kal") is not None
    assert fts.stats()["count"] >= 1


@pytest.mark.asyncio
async def test_full_decision_persistent_cache_hit_skips_live_fetch(monkeypatch):
    """Kalıcı cache'te varsa CANLI ÇEKİŞ YAPILMAZ (anında diskten)."""
    fd._cache.clear()
    key = "https://x|id9"  # fetch_full_decision'ın kurduğu key formatı
    await fts.put(key, "ÖNCEDEN çekilmiş tam karar metni yeterince uzun burada olsun.")
    called = {"yargi": False}

    async def fake_yargi(*_a, **_k):
        called["yargi"] = True
        return "", "not_found"

    monkeypatch.setattr(fd, "_fetch_yargi_text", fake_yargi)
    r = await fd.fetch_full_decision("https://x", "id9")
    assert r["cached"] is True and "ÖNCEDEN" in r["text"]
    assert called["yargi"] is False  # cache hit → yavaş çekiş atlandı


@pytest.mark.asyncio
async def test_concurrent_puts_no_lock_error():
    """20 eşzamanlı put + get — Windows+WAL 'database is locked' regresyonunu yakalar."""
    await asyncio.gather(*[fts.put(f"ck{i}", _LONG + str(i)) for i in range(20)])
    got = await asyncio.gather(*[fts.get(f"ck{i}") for i in range(20)])
    assert all(g is not None for g in got)  # hepsi yazıldı + okundu (kilit hatası yok)


@pytest.mark.asyncio
async def test_fail_open_on_unwritable_db(monkeypatch, tmp_path):
    """DB yolu açılamazsa (dizin) → get None, put sessiz no-op (fail-open sözleşmesi)."""
    monkeypatch.setenv("FULLTEXT_CACHE_PATH", str(tmp_path))  # dizin → sqlite açamaz
    await fts.put("x", _LONG)        # patlamamalı
    assert await fts.get("x") is None  # okuma da fail-open


@pytest.mark.asyncio
async def test_lru_pruning_caps_rows(monkeypatch):
    """Tavanı aşınca en eski fetched_at'ler budanır → satır sayısı sabit kalır."""
    monkeypatch.setattr(fts, "_MAX_ROWS", 3)
    for i in range(5):
        await fts.put(f"lru{i}", _LONG)
        await asyncio.sleep(0.02)  # distinct fetched_at (Windows time çözünürlüğü)
    assert fts.stats()["count"] == 3
    assert await fts.get("lru4") is not None  # en yeni duruyor
    assert await fts.get("lru0") is None      # en eski budandı


def test_normalized_cache_key_stable_and_collision_safe():
    """Aynı karar farklı URL/param → TEK key; rakamsız → fallback."""
    k1 = fd._normalized_cache_key("https://karararama.yargitay.gov.tr/?aranan=454053700", "h-454053700-c3")
    k2 = fd._normalized_cache_key("https://karararama.yargitay.gov.tr/?x=1&aranan=454053700", "h-454053700-c9")
    assert k1 == k2  # farklı param/chunk → aynı karar → aynı key
    assert "454053700" in k1
    # rakamsız kaynak → ham fallback (eski format korunur)
    assert fd._normalized_cache_key("https://x", "id") == "https://x|id"


@pytest.mark.asyncio
async def test_full_decision_writes_live_result_to_persistent_cache(monkeypatch):
    """Canlı çekiş başarısı kalıcı cache'e yazılır → in-process temizlense de diskten gelir."""
    fd._cache.clear()

    async def fake_yargi(*_a, **_k):
        return "YENİ çekilen tam karar metni yeterince uzun olsun burada gerçekten.", None

    monkeypatch.setattr(fd, "_fetch_yargi_text", fake_yargi)
    r1 = await fd.fetch_full_decision("https://y", "id10")
    assert r1["error"] is None and r1["cached"] is False and "YENİ" in r1["text"]

    fd._cache.clear()  # process restart simülasyonu (in-process cache uçtu)
    r2 = await fd.fetch_full_decision("https://y", "id10")
    assert r2["cached"] is True and "YENİ" in r2["text"]
