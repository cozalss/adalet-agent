"""W7.5 — Multimodal upload security testleri."""

from __future__ import annotations

import pytest

from api.routes.multimodal import (
    _ALLOWED_AUDIO_MIMES,
    _base_mime,
    _detect_audio_kind,
    _detect_image_kind,
    _sanitize_filename,
)


@pytest.mark.parametrize("content_type,expected", [
    ("audio/webm;codecs=opus", "audio/webm"),   # MediaRecorder blob (mikrofon STT 415 kök-nedeni)
    ("audio/webm; codecs=opus", "audio/webm"),  # boşluklu parametre
    ("audio/ogg;codecs=opus", "audio/ogg"),
    ("audio/wav", "audio/wav"),                 # parametresiz değişmez
    ("AUDIO/WEBM", "audio/webm"),               # büyük-küçük normalize
    (None, ""),
    ("", ""),
])
def test_base_mime_strips_parameters(content_type, expected):
    assert _base_mime(content_type) == expected


def test_base_mime_webm_opus_passes_allowlist():
    """MediaRecorder 'audio/webm;codecs=opus' allowlist'e takılmamalı (mikrofon STT fix)."""
    assert _base_mime("audio/webm;codecs=opus") in _ALLOWED_AUDIO_MIMES


@pytest.mark.parametrize("raw,expected_safe", [
    ("normal.png", "normal.png"),
    ("../../../etc/passwd", "etcpasswd"),
    ("..\\..\\windows\\system32", "windowssystem32"),
    ("file\x00null.png", "filenull.png"),
    ("file with spaces.png", "file_with_spaces.png"),
    ("üçgen.jpg", "_gen.jpg"),  # non-ASCII stripped
    ("", "image"),  # empty → default
    (None, "image"),  # None → default
    (".....", "image"),  # only dots → default
    ("a" * 200 + ".png", ("a" * 124 + ".png")[:128]),  # truncate
])
def test_sanitize_filename(raw, expected_safe):
    out = _sanitize_filename(raw, "image")
    if expected_safe == "image":
        assert out == "image"
    else:
        # Doğrulamalar: path bileşeni yok, null byte yok, len <= 128
        assert "/" not in out
        assert "\\" not in out
        assert "\x00" not in out
        assert ".." not in out
        assert len(out) <= 128


def test_sanitize_filename_no_path_traversal():
    """Path traversal pattern'i hiçbir output'ta yok."""
    for evil in (
        "../etc/passwd",
        "../../root/.ssh/id_rsa",
        "..\\..\\boot.ini",
        "/etc/shadow",
        "C:\\Windows\\System32\\config\\SAM",
    ):
        out = _sanitize_filename(evil, "default")
        assert "/" not in out
        assert "\\" not in out
        assert ":" not in out


# --- H1: magic-byte tabanlı dosya türü doğrulaması ---

def test_detect_image_kind_valid_signatures():
    """Geçerli görüntü/PDF magic byte'ları doğru tanınır."""
    cases = {
        "jpeg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x02\x03",
        "png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0d",
        "webp": b"RIFF\x24\x00\x00\x00WEBPVP8 ",
        "tiff": b"II*\x00\x08\x00\x00\x00\x00\x00\x00\x00",
        "pdf": b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n",
    }
    for expected, data in cases.items():
        assert _detect_image_kind(data) == expected


def test_detect_image_kind_rejects_fake_mime():
    """Sahte içerik (HTML/SVG/script polyglot) reddedilir — None döner."""
    for evil in (
        b"<html><body>not an image</body></html>",
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        b"#!/bin/sh\nrm -rf /\n",
        b"GIF89a",  # GIF whitelist'te yok → desteklenmez
        b"\x00\x01\x02",  # çok kısa
        b"",
    ):
        assert _detect_image_kind(evil) is None


def test_detect_audio_kind_valid_signatures():
    """Geçerli ses magic byte'ları doğru tanınır (STT input-validation)."""
    cases = {
        "wav": b"RIFF\x24\x08\x00\x00WAVEfmt ",
        "ogg": b"OggS\x00\x02\x00\x00\x00\x00\x00\x00",
        "flac": b"fLaC\x00\x00\x00\x22\x00\x00\x00\x00",
        "webm": b"\x1aE\xdf\xa3\x9fB\x86\x81\x01\x00\x00\x00",
        "mp4": b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00",
        "mp3": b"ID3\x04\x00\x00\x00\x00\x00\x00\x00\x00",
    }
    for expected, data in cases.items():
        assert _detect_audio_kind(data) == expected
    # MP3 frame-sync (ID3 tag'sız) da tanınmalı
    assert _detect_audio_kind(b"\xff\xfb\x90\x00" + b"\x00" * 8) == "mp3"


def test_detect_audio_kind_rejects_fake_mime():
    """Sahte/çok-kısa içerik reddedilir — None (Whisper'a bozuk içerik gitmesin)."""
    for evil in (
        b"<html>not audio</html>\x00\x00\x00",
        b"#!/bin/sh\nrm -rf /\n",
        b"RIFF\x00\x00\x00\x00AVI ",   # RIFF ama WAVE değil (AVI)
        b"\x00\x01\x02",                # çok kısa
        b"",
    ):
        assert _detect_audio_kind(evil) is None


def test_security_headers_present():
    """SecurityHeadersMiddleware her response'a güvenlik başlıklarını ekler.

    İzole minimal app — main.app lifespan/preload'unu tetiklemeden middleware'i
    doğrular (unit test).
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.middleware.security_headers import SecurityHeadersMiddleware

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def _ping() -> dict:
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/ping")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in r.headers


def test_security_headers_hsts_toggle(monkeypatch):
    """HSTS yalnız SECURITY_HSTS_ENABLED=1 ile eklenir (default kapalı)."""
    import importlib

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SECURITY_HSTS_ENABLED", "1")
    import api.middleware.security_headers as sh_mod
    importlib.reload(sh_mod)

    app = FastAPI()
    app.add_middleware(sh_mod.SecurityHeadersMiddleware)

    @app.get("/ping")
    def _ping() -> dict:
        return {"ok": True}

    r = TestClient(app).get("/ping")
    assert "max-age=31536000" in r.headers.get("Strict-Transport-Security", "")
    # cleanup — modülü default state'e geri döndür
    monkeypatch.delenv("SECURITY_HSTS_ENABLED", raising=False)
    importlib.reload(sh_mod)
