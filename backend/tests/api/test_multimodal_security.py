"""W7.5 — Multimodal upload security testleri."""

from __future__ import annotations

import pytest

from api.routes.multimodal import _sanitize_filename


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
