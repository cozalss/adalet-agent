"""Firecrawl tam-metin yedeği — host allowlist, anahtar guard, scrape + fetch_full_decision yedeği.
Gerçek ağ YOK (httpx mock). conftest FIRECRAWL_API_KEY'i her test kendi kontrol eder."""
from __future__ import annotations

import pytest

import retrieval.firecrawl_client as fc
import retrieval.full_decision as fd


def test_host_allowed_allowlist_and_spoof():
    assert fc.host_allowed("https://www.mevzuat.gov.tr/x")
    assert fc.host_allowed("https://emsal.uyap.gov.tr/x")
    assert fc.host_allowed("https://kararlarbilgibankasi.anayasa.gov.tr/x")
    # SSRF spoof: substring eşleşmesi DEĞİL, tam host
    assert not fc.host_allowed("https://evil.com/anayasa.gov.tr")
    assert not fc.host_allowed("https://example.com")
    assert not fc.host_allowed("")


def test_firecrawl_enabled_reflects_key(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    assert fc.firecrawl_enabled() is False
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-x")
    assert fc.firecrawl_enabled() is True


def _install_httpx(monkeypatch, markdown: str):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": True, "data": {"markdown": markdown}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(fc.httpx, "AsyncClient", _Client)


@pytest.mark.asyncio
async def test_scrape_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    assert await fc.scrape_legal_url("https://www.mevzuat.gov.tr/x") == ""


@pytest.mark.asyncio
async def test_scrape_host_not_allowed_returns_empty(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-x")
    assert await fc.scrape_legal_url("https://evil.com/x") == ""


@pytest.mark.asyncio
async def test_scrape_success_and_short_guard(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-x")
    _install_httpx(monkeypatch, "Resmî karar metni " * 10)
    out = await fc.scrape_legal_url("https://www.mevzuat.gov.tr/x")
    assert out.startswith("Resmî karar metni")
    # çok kısa markdown → "" (anlamlı metin değil)
    _install_httpx(monkeypatch, "kısa")
    assert await fc.scrape_legal_url("https://www.mevzuat.gov.tr/x") == ""


@pytest.mark.asyncio
async def test_full_decision_firecrawl_fallback_on_not_found(monkeypatch):
    """yargi-mcp not_found + Firecrawl metin → cevap Firecrawl metniyle döner (error=None)."""
    fd._cache.clear()

    async def fake_yargi(*_a, **_k):
        return "", "not_found"

    async def fake_scrape(url, *, timeout_s=30.0):
        return "FIRECRAWL kararın tam metni. " * 5

    monkeypatch.setattr(fd, "_fetch_yargi_text", fake_yargi)
    monkeypatch.setattr("retrieval.firecrawl_client.scrape_legal_url", fake_scrape)
    r = await fd.fetch_full_decision("https://www.mevzuat.gov.tr/x", "id-1")
    assert r["error"] is None
    assert "FIRECRAWL" in r["text"]


@pytest.mark.asyncio
async def test_full_decision_keeps_error_when_firecrawl_empty(monkeypatch):
    """Firecrawl de getiremezse (anahtar yok/host izinsiz) orijinal hata korunur."""
    fd._cache.clear()

    async def fake_yargi(*_a, **_k):
        return "", "rate_limited"

    async def fake_scrape(url, *, timeout_s=30.0):
        return ""

    monkeypatch.setattr(fd, "_fetch_yargi_text", fake_yargi)
    monkeypatch.setattr("retrieval.firecrawl_client.scrape_legal_url", fake_scrape)
    r = await fd.fetch_full_decision("https://www.mevzuat.gov.tr/x", "id-2")
    assert r["error"] == "rate_limited" and r["text"] == ""
