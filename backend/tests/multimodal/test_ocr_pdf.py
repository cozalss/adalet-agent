"""extract_text PDF + RapidOCR yönlendirme testleri.

RapidOCR motoru mock'lanır (model yükleme/flakiness olmadan yönlendirme test edilir);
PDF metin çıkarımı gerçek PyMuPDF ile koşar. Paylaşılan fixture'lar: conftest.py
"""

from __future__ import annotations

import pytest

pytest.importorskip("fitz")

import multimodal.ocr as ocr
from multimodal.ocr import extract_text
from tests.multimodal.conftest import needs_turkish_font


@needs_turkish_font
@pytest.mark.asyncio
async def test_digital_pdf_uses_text_layer_no_ocr(make_digital_pdf):
    """Dijital PDF → engine=pdf-text, Türkçe korunur, OCR çağrılmaz."""
    text_in = "Kıdem tazminatı şartları: işçi en az bir yıl çalışmış olmalıdır."
    r = await extract_text(make_digital_pdf(text_in))
    assert r.engine == "pdf-text"
    assert "Kıdem" in r.text and "şartları" in r.text
    assert r.page_count == 1
    assert r.error is None


@pytest.mark.asyncio
async def test_scanned_pdf_routes_to_rapidocr(monkeypatch, make_scanned_pdf):
    """Metin katmanı yok → sayfa render edilip RapidOCR'a verilir."""
    monkeypatch.setattr(
        ocr, "rapidocr_image", lambda _b: ("Taranmis belge metni", 0.88, None),
    )
    r = await extract_text(make_scanned_pdf())
    assert r.engine == "pdf-scan-rapidocr"
    assert "Taranmis belge metni" in r.text
    assert r.confidence == 0.88
    assert r.error is None


@pytest.mark.asyncio
async def test_image_routes_to_rapidocr_by_default(monkeypatch, png_bytes):
    """Görsel (PDF değil) → varsayılan motor RapidOCR."""
    monkeypatch.setattr(
        ocr, "rapidocr_image", lambda _b: ("Kira sozlesmesi", 0.95, None),
    )
    r = await extract_text(png_bytes)
    assert r.engine == "rapidocr"
    assert "Kira sozlesmesi" in r.text


@pytest.mark.asyncio
async def test_weak_fallback_keeps_short_text_when_qwen_disabled(monkeypatch, png_bytes):
    """Regresyon guard: kısa-ama-geçerli RapidOCR sonucu, disabled Qwen fallback'le EZİLMEZ."""
    monkeypatch.delenv("OCR_QWEN_VL_ENABLED", raising=False)
    monkeypatch.setattr(ocr, "rapidocr_image", lambda _b: ("Madde 5", 0.9, None))
    r = await extract_text(png_bytes)  # auto mode
    # Qwen disabled → boş+error döner; kısa metin korunmalı
    assert r.text == "Madde 5"
    assert r.error is None


@pytest.mark.asyncio
async def test_scanned_pdf_no_text_returns_helpful_error(monkeypatch, make_scanned_pdf):
    """Tarama OCR'ı da boş dönerse kullanıcıya anlamlı hata."""
    monkeypatch.setattr(ocr, "rapidocr_image", lambda _b: ("", None, None))
    r = await extract_text(make_scanned_pdf())
    assert r.text == ""
    assert r.error is not None


@pytest.mark.asyncio
async def test_corrupt_pdf_returns_error_not_crash():
    r = await extract_text(b"%PDF-1.7 bozuk icerik degil bu")
    assert r.text == ""
    assert r.error is not None
    assert "PDF" in (r.error or "")


@pytest.mark.asyncio
async def test_qwen_disabled_error_does_not_leak_env_var_name(monkeypatch, png_bytes):
    """GÜVENLİK: qwen-vl kapalı hatası iç ENV değişken adını sızdırmamalı."""
    monkeypatch.delenv("OCR_QWEN_VL_ENABLED", raising=False)
    r = await extract_text(png_bytes, engine="qwen-vl")
    assert r.error is not None
    assert "OCR_QWEN_VL_ENABLED" not in r.error  # ENV adı sızmadı
