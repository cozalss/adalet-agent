"""Paylaşılan PDF test fixture'ları — test_pdf_utils + test_ocr_pdf ortak kullanır.

Windows arial.ttf yoksa (Linux CI) Türkçe-glif gerektiren testler skip edilir.
"""

from __future__ import annotations

import io
import pathlib

import pytest

fitz = pytest.importorskip("fitz")

_FONT = "C:/Windows/Fonts/arial.ttf"
_HAS_FONT = pathlib.Path(_FONT).exists()
_TR = "Madde 11 - İşçi kıdem tazminatına hak kazanır. Ayşe Yılmaz İstanbul."

# Türkçe-glif gerektiren testlerde kullan: @needs_turkish_font
needs_turkish_font = pytest.mark.skipif(
    not _HAS_FONT, reason="Türkçe glifli font (arial.ttf) yok — diakritik testi atlanır",
)


@pytest.fixture
def turkish_text() -> str:
    return _TR


@pytest.fixture
def make_digital_pdf():
    """Gömülü metin katmanı olan PDF üreten factory (text, pages)."""
    def _make(text: str = _TR, pages: int = 1) -> bytes:
        doc = fitz.open()
        for _ in range(pages):
            page = doc.new_page()
            if _HAS_FONT:
                page.insert_textbox(
                    fitz.Rect(36, 36, 560, 760), text,
                    fontsize=14, fontfile=_FONT, fontname="arial",
                )
            else:  # font yoksa varsayılan (diakritik bozulabilir ama metin katmanı oluşur)
                page.insert_textbox(fitz.Rect(36, 36, 560, 760), text, fontsize=14)
        out = doc.tobytes()
        doc.close()
        return out
    return _make


@pytest.fixture
def make_scanned_pdf():
    """Metin katmanı OLMAYAN PDF (yalnız gömülü görsel) üreten factory."""
    def _make() -> bytes:
        from PIL import Image
        bio = io.BytesIO()
        Image.new("RGB", (400, 200), "white").save(bio, format="PNG")
        doc = fitz.open()
        page = doc.new_page(width=400, height=200)
        page.insert_image(fitz.Rect(0, 0, 400, 200), stream=bio.getvalue())
        out = doc.tobytes()
        doc.close()
        return out
    return _make


@pytest.fixture
def make_oversized_pdf():
    """GÜVENLİK testi: devasa MediaBox'lı PDF (pixmap bellek bombası)."""
    def _make(dim_pt: int = 20000) -> bytes:
        doc = fitz.open()
        doc.new_page(width=dim_pt, height=dim_pt)
        out = doc.tobytes()
        doc.close()
        return out
    return _make


@pytest.fixture
def png_bytes():
    """Küçük geçerli PNG byte'ları."""
    from PIL import Image
    bio = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(bio, format="PNG")
    return bio.getvalue()
