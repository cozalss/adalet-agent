"""Dilekçe indirme + silme endpoint testleri — auth + ownership + cache cap."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from api.dilekce_store import _DilekceCache, clear_cache, store_pdf
from main import app


@pytest.fixture(autouse=True)
def _clear_dilekce_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture(autouse=True)
def _disable_auth_for_tests(monkeypatch):
    """AUTH_ENABLED=0 → ownership atlanır (test fixture). Production'da auth zorunlu."""
    monkeypatch.setenv("AUTH_ENABLED", "0")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _valid_uuid() -> str:
    # GERÇEK biçim: backend conversation_id'yi uuid4().hex (TİRESİZ) üretir. Testler
    # eskiden str(uuid.uuid4()) (tireli) kullanıp gerçek indirme akışını kaçırıyordu.
    return uuid.uuid4().hex


# --- conversation_id format sözleşmesi (denetim 2026-06-04: gerçek ID bug'ı) ---

def test_uuid_re_accepts_real_backend_conversation_id():
    """REGRESYON: _new_conversation_id()'nin ÜRETTİĞİ ID, dilekçe endpoint'inin KABUL
    ettiği biçim olmalı. Eski tireli-only regex gerçek uuid4().hex'i 400'lüyordu."""
    from api.routes.ask import _new_conversation_id
    from api.routes.dilekce import _UUID_RE

    real_id = _new_conversation_id()
    assert "-" not in real_id and len(real_id) == 32  # uuid4().hex sözleşmesi
    assert _UUID_RE.match(real_id), "gerçek conversation_id endpoint regex'ini geçmeli"


def test_uuid_re_accepts_both_forms_rejects_traversal():
    from api.routes.dilekce import _UUID_RE

    assert _UUID_RE.match(uuid.uuid4().hex)          # tiresiz (gerçek)
    assert _UUID_RE.match(str(uuid.uuid4()))         # tireli (legacy/canonical)
    for bad in ("../etc/passwd", "abc", "g" * 32, "../../x", "%2e%2e", ""):
        assert not _UUID_RE.match(bad), f"geçersiz ID kabul edildi: {bad!r}"


# --- Endpoint güvenliği ---

def test_get_pdf_404_when_missing(client):
    resp = client.get(f"/api/dilekce/{_valid_uuid()}")
    assert resp.status_code == 404


def test_get_pdf_400_when_invalid_conversation_id(client):
    """Path traversal koruması: UUID4 dışı format reddedilir."""
    resp = client.get("/api/dilekce/not-a-uuid")
    assert resp.status_code == 400


def test_get_pdf_happy_path_streams_bytes(client):
    cid = _valid_uuid()
    fake_pdf = b"%PDF-1.4 test content"
    store_pdf(cid, fake_pdf, "test.pdf", "tuketici/x_v1", owner_sub="test-user")
    resp = client.get(f"/api/dilekce/{cid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert "test.pdf" in resp.headers["content-disposition"]
    # template_id RESPONSE header'da SIZDIRILMAZ (security-reviewer öneri #5)
    assert "x-dilekce-template" not in {k.lower() for k in resp.headers}
    assert resp.content == fake_pdf


def test_get_pdf_filename_must_be_ascii(client):
    """Türkçe karakter Content-Disposition'a sızmamalı."""
    cid = _valid_uuid()
    store_pdf(
        cid, b"%PDF-1.4", "dilekce-tuketici-2026-05-28.pdf", "x",
        owner_sub="test-user",
    )
    resp = client.get(f"/api/dilekce/{cid}")
    assert resp.status_code == 200
    cd = resp.headers["content-disposition"]
    assert cd.isascii(), f"Non-ASCII in Content-Disposition: {cd}"


# --- DOCX endpoint ---

_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_get_docx_happy_path(client):
    cid = _valid_uuid()
    store_pdf(cid, b"%PDF-1.4", "d.pdf", "isHukuku/x_v1", owner_sub="test-user",
              docx_bytes=b"PK\x03\x04 fake docx", docx_filename="d.docx")
    resp = client.get(f"/api/dilekce/{cid}/docx")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == _DOCX_MEDIA
    assert "d.docx" in resp.headers["content-disposition"]
    assert resp.content == b"PK\x03\x04 fake docx"


def test_get_docx_404_when_no_docx(client):
    """PDF var ama DOCX üretilmemiş → 404."""
    cid = _valid_uuid()
    store_pdf(cid, b"%PDF-1.4", "d.pdf", "x", owner_sub="test-user")  # docx yok
    resp = client.get(f"/api/dilekce/{cid}/docx")
    assert resp.status_code == 404


def test_get_docx_404_when_missing(client):
    resp = client.get(f"/api/dilekce/{_valid_uuid()}/docx")
    assert resp.status_code == 404


def test_get_docx_400_invalid_uuid(client):
    resp = client.get("/api/dilekce/not-a-uuid/docx")
    assert resp.status_code == 400


def test_get_docx_ownership_enforced(monkeypatch, client):
    monkeypatch.setenv("AUTH_ENABLED", "1")
    cid = _valid_uuid()
    store_pdf(cid, b"%PDF-1.4", "d.pdf", "x", owner_sub="alice",
              docx_bytes=b"PK\x03\x04", docx_filename="d.docx")
    resp = client.get(f"/api/dilekce/{cid}/docx")
    assert resp.status_code in {401, 403}


# --- IDOR / Ownership ---

def test_ownership_blocks_other_user_when_auth_enabled(monkeypatch, client):
    """AUTH_ENABLED=1 ortamında başka kullanıcının PDF'ine erişilemez (403)."""
    monkeypatch.setenv("AUTH_ENABLED", "1")
    cid = _valid_uuid()
    store_pdf(cid, b"%PDF-1.4", "x.pdf", "x", owner_sub="alice")
    # AUTH_ENABLED=1 dev token "anonymous" kabul eder; principal.sub != "alice"
    resp = client.get(f"/api/dilekce/{cid}")
    # 401 (auth fail) ya da 403 (ownership fail) bekleriz; mock auth'a göre.
    assert resp.status_code in {401, 403}


# --- KVKK Silme ---

def test_delete_pdf_removes_from_cache(client):
    cid = _valid_uuid()
    store_pdf(cid, b"%PDF-1.4", "x.pdf", "x", owner_sub="test-user")
    resp = client.delete(f"/api/dilekce/{cid}")
    assert resp.status_code == 204
    # İkinci GET 404 — gerçekten silinmiş
    resp2 = client.get(f"/api/dilekce/{cid}")
    assert resp2.status_code == 404


def test_delete_pdf_404_when_missing(client):
    resp = client.delete(f"/api/dilekce/{_valid_uuid()}")
    assert resp.status_code == 404


# --- Cache LRU + bound ---

def test_cache_lru_evicts_oldest():
    """max_entries aşıldığında en eski kayıt silinir (LRU)."""
    cache = _DilekceCache(ttl_s=3600, max_entries=3)
    for i in range(5):
        cache.store(f"cid-{i:08x}", b"%PDF-1.4", "x.pdf", "x", owner_sub="u")
    # En son 3'ü kalmalı (cid-2, 3, 4)
    assert cache.size == 3
    assert cache.get("cid-00000000") is None  # evicted
    assert cache.get("cid-00000004") is not None  # newest


def test_cache_get_returns_none_after_ttl():
    """TTL geçince get() None döner ve girdi silinir."""
    import api.dilekce_store as store_mod
    cache = _DilekceCache(ttl_s=1, max_entries=10)
    cache.store("c1", b"%PDF", "x.pdf", "x", owner_sub="u")
    assert cache.get("c1") is not None
    # Saatçi: cache içindeki entry.expires_at zaten "şimdi + 1s"; gerçek zaman
    # yerine modülün time.time() referansını ileri zıplat.
    orig_time = store_mod.time.time
    store_mod.time.time = lambda: orig_time() + 5  # type: ignore[method-assign]
    try:
        assert cache.get("c1") is None
    finally:
        store_mod.time.time = orig_time  # type: ignore[method-assign]
