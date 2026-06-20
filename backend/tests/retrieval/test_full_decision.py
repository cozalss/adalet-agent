"""full_decision — karar TAM metnini canlı çek (document_id çıkarımı + fetch yönlendirme).

Ağ YOK: YargiClient mock'lanır. document_id çıkarımı fizibilite-doğrulanmış kuralla
(source_url ?aranan= / chunk_id) test edilir.
"""

from __future__ import annotations

import pytest

import retrieval.full_decision as fd
from retrieval.full_decision import bedesten_document_id, fetch_full_decision


@pytest.fixture(autouse=True)
def _clear_cache_and_fast_retry(monkeypatch):
    fd._cache.clear()
    monkeypatch.setattr(fd, "_RATE_LIMIT_RETRY_DELAY_S", 0.0)  # testte 2s bekleme yok
    yield
    fd._cache.clear()


class _FakeYC:
    """Async-context YargiClient taklidi; get_* sıralı/sabit metin döndürür."""

    def __init__(self, results):
        self._results = list(results) if isinstance(results, (list, tuple)) else [results]
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def _next(self):
        self.calls += 1
        return self._results[min(self.calls - 1, len(self._results) - 1)]

    async def get_document(self, document_id):
        return await self._next()

    async def get_emsal_document(self, document_id):
        return await self._next()

    async def get_anayasa_document(self, url):
        return await self._next()


def _patch_yc(monkeypatch, results):
    monkeypatch.setattr("retrieval.yargi_client.YargiClient", lambda *_a, **_k: _FakeYC(results))


# --- document_id çıkarımı ---

def test_document_id_from_aranan_url():
    assert bedesten_document_id("https://karararama.yargitay.gov.tr/?aranan=525485900", "") == "525485900"


def test_document_id_from_chunk_id_fallback():
    assert bedesten_document_id("", "h-525485900-c14") == "525485900"
    assert bedesten_document_id("", "h-1029169000-c4") == "1029169000"


def test_document_id_none_when_no_signal():
    assert bedesten_document_id("", "") == ""
    assert bedesten_document_id("https://example.com/x", "abc") == ""


# --- fetch_full_decision ---

@pytest.mark.asyncio
async def test_fetch_success_returns_full_text(monkeypatch):
    body = "**8. Hukuk Dairesi 2011/5172 E.** İçtihat Metni: " + "x" * 200
    _patch_yc(monkeypatch, body)
    out = await fetch_full_decision("https://karararama.yargitay.gov.tr/?aranan=525485900", "h-525485900-c1")
    assert out["error"] is None
    assert out["text"] == body
    assert out["cached"] is False


@pytest.mark.asyncio
async def test_fetch_not_found_for_empty(monkeypatch):
    _patch_yc(monkeypatch, "")
    out = await fetch_full_decision("https://karararama.yargitay.gov.tr/?aranan=1", "")
    assert out["text"] == "" and out["error"] == "not_found"


@pytest.mark.asyncio
async def test_fetch_rate_limited_detected(monkeypatch):
    # yargi-mcp rate-limit'i İÇERİK olarak döndürür → tespit + (her iki denemede de) error.
    rl = "ERROR (rate_limit_exceeded, HTTP 429): Bedesten istemci eşzamanlılık sınırı"
    _patch_yc(monkeypatch, [rl, rl])
    out = await fetch_full_decision("https://karararama.yargitay.gov.tr/?aranan=2", "")
    assert out["error"] == "rate_limited" and out["text"] == ""


@pytest.mark.asyncio
async def test_fetch_rate_limit_then_retry_success(monkeypatch):
    rl = "ERROR (rate_limit_exceeded, HTTP 429): dolu"
    good = "Gerçek içtihat metni " + "y" * 100
    _patch_yc(monkeypatch, [rl, good])   # ilk rate-limit, retry başarılı
    out = await fetch_full_decision("https://karararama.yargitay.gov.tr/?aranan=3", "")
    assert out["error"] is None and out["text"] == good


@pytest.mark.asyncio
async def test_fetch_http_429_maps_to_rate_limited(monkeypatch):
    # HTTP 429 (içerik değil status) → retry tükenince jenerik değil 'rate_limited'.
    import httpx

    class _YC429(_FakeYC):
        async def get_document(self, document_id):
            req = httpx.Request("POST", "https://x")
            raise httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, request=req))

    monkeypatch.setattr("retrieval.yargi_client.YargiClient", lambda *_a, **_k: _YC429([""]))
    out = await fetch_full_decision("https://karararama.yargitay.gov.tr/?aranan=9", "")
    assert out["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_fetch_cache_hit_second_call(monkeypatch):
    body = "İçtihat metni " + "z" * 100
    _patch_yc(monkeypatch, body)
    first = await fetch_full_decision("https://karararama.yargitay.gov.tr/?aranan=525485900", "")
    second = await fetch_full_decision("https://karararama.yargitay.gov.tr/?aranan=525485900", "")
    assert first["cached"] is False and second["cached"] is True
    assert second["text"] == body


@pytest.mark.asyncio
async def test_fetch_falls_back_to_public_when_local_mcp_down(monkeypatch):
    # .env yerel mcp'ye (127.0.0.1:8765) işaret eder; kapalıysa ConnectError → public'e düş.
    import httpx
    good = "Public mcp içtihat metni " + "p" * 100
    attempts: list = []

    class _ConnFail:
        async def __aenter__(self):
            raise httpx.ConnectError("connection refused")

        async def __aexit__(self, *exc):
            return False

    def factory(*a, **k):
        base = k.get("base_url")
        attempts.append(base)
        return _ConnFail() if base is None else _FakeYC(good)

    monkeypatch.setattr("retrieval.yargi_client.YargiClient", factory)
    out = await fetch_full_decision("https://karararama.yargitay.gov.tr/?aranan=525485900", "")
    assert out["error"] is None and out["text"] == good
    assert attempts == [None, "https://yargimcp.surucu.dev/mcp"]  # önce yerel, sonra public


@pytest.mark.asyncio
async def test_fetch_unknown_domain_no_fetch_ssrf(monkeypatch):
    # Keyfi/zararlı url + çıkarılabilir id YOK → hiçbir kaynakla eşleşmez → fetch edilmez.
    called = {"n": 0}

    class _Spy(_FakeYC):
        async def _next(self):
            called["n"] += 1
            return await super()._next()

    monkeypatch.setattr("retrieval.yargi_client.YargiClient", lambda *_a, **_k: _Spy(["zararlı içerik"]))
    out = await fetch_full_decision("https://evil.example.com/leak", "no-digits-here")
    assert out["error"] == "not_found"
    assert called["n"] == 0  # hiç fetch çağrısı yapılmadı


@pytest.mark.asyncio
async def test_anayasa_host_spoof_not_fetched(monkeypatch):
    # ECC HIGH: substring spoof 'evil.com/anayasa.gov.tr' anayasa'ya GİTMEMELİ (host tam-eşleşme).
    called = {"anayasa": 0}

    class _Spy(_FakeYC):
        async def get_anayasa_document(self, url):
            called["anayasa"] += 1
            return await self._next()

    monkeypatch.setattr("retrieval.yargi_client.YargiClient", lambda *_a, **_k: _Spy(["sızdırılan"]))
    out = await fetch_full_decision("https://evil.com/anayasa.gov.tr/x", "no-digit")
    assert called["anayasa"] == 0       # spoof → anayasa fetch YOK
    assert out["error"] == "not_found"


@pytest.mark.asyncio
async def test_real_anayasa_host_routes_to_anayasa(monkeypatch):
    called = {"anayasa": 0}

    class _Spy(_FakeYC):
        async def get_anayasa_document(self, url):
            called["anayasa"] += 1
            return await self._next()

    monkeypatch.setattr(
        "retrieval.yargi_client.YargiClient",
        lambda *_a, **_k: _Spy(["AYM kararı tam metni " + "a" * 80]),
    )
    out = await fetch_full_decision("https://kararlarbilgibankasi.anayasa.gov.tr/BB/2014/2267", "")
    assert called["anayasa"] == 1 and out["error"] is None
