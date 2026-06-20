"""PDF yardımcıları — dijital metin çıkarımı + tarama render + güvenlik testleri.

Gerçek PyMuPDF (fitz) kullanır — hızlı, deterministik, model gerekmez.
Paylaşılan fixture'lar: tests/multimodal/conftest.py
"""

from __future__ import annotations

import pytest

pytest.importorskip("fitz")  # PyMuPDF kurulu değilse atla

from multimodal.pdf_utils import (
    MAX_RENDER_PIXELS,
    extract_pdf_text,
    is_pdf,
    render_pdf_to_images,
)
from tests.multimodal.conftest import needs_turkish_font


def test_is_pdf_detects_magic_bytes():
    assert is_pdf(b"%PDF-1.7\n...")
    assert not is_pdf(b"\x89PNG\r\n\x1a\n")
    assert not is_pdf(b"")
    assert not is_pdf(b"%PD")  # çok kısa


@needs_turkish_font
def test_extract_pdf_text_digital_preserves_turkish(make_digital_pdf):
    text, pages = extract_pdf_text(make_digital_pdf())
    assert pages == 1
    assert "İşçi" in text
    assert "kıdem" in text
    assert "Ayşe" in text


def test_extract_pdf_text_scanned_returns_empty(make_scanned_pdf):
    """Metin katmanı yok → "" döner (çağıran render+OCR yoluna düşer)."""
    text, pages = extract_pdf_text(make_scanned_pdf())
    assert text == ""
    assert pages == 1


def test_extract_pdf_text_corrupt_returns_empty_not_crash():
    text, pages = extract_pdf_text(b"%PDF-1.7 bu bozuk bir pdf degil")
    assert text == ""
    assert pages == 0


def test_extract_pdf_text_respects_max_pages(make_digital_pdf):
    text, pages = extract_pdf_text(make_digital_pdf(pages=5), max_pages=2)
    assert pages == 5  # toplam sayfa raporlanır
    # Yalnız 2 sayfa işlendiği için metin 5 sayfalıktan kısa (cap çalıştı)
    full, _ = extract_pdf_text(make_digital_pdf(pages=5), max_pages=10)
    assert len(text) < len(full)


def test_render_pdf_to_images_returns_png_per_page(make_digital_pdf):
    images = render_pdf_to_images(make_digital_pdf(pages=3))
    assert len(images) == 3
    for png in images:
        assert png[:8] == b"\x89PNG\r\n\x1a\n"  # geçerli PNG imzası


def test_render_pdf_to_images_respects_max_pages(make_digital_pdf):
    images = render_pdf_to_images(make_digital_pdf(pages=5), max_pages=2)
    assert len(images) == 2


def test_render_corrupt_pdf_returns_empty_list():
    assert render_pdf_to_images(b"%PDF-bozuk") == []


def test_render_skips_oversized_page_memory_bomb(make_oversized_pdf):
    """GÜVENLİK: devasa MediaBox'lı sayfa render EDİLMEDEN atlanmalı (OOM guard)."""
    # 20000pt² @200dpi ≈ 3.1 milyar piksel → MAX_RENDER_PIXELS'i kat kat aşar.
    images = render_pdf_to_images(make_oversized_pdf(dim_pt=20000))
    assert images == []  # render edilmedi → OOM olmadı


def test_max_render_pixels_threshold_is_sane():
    # PIL decompression-bomb guard'ı ile aynı mertebede (~40-50M).
    assert 10_000_000 <= MAX_RENDER_PIXELS <= 100_000_000
