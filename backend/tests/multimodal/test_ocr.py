"""OCR — extract_text testleri.

Gerçek Tesseract binary'si test ortamında kurulu olabilir veya olmayabilir.
Fallback yolu (PIL/pytesseract yok) ve ana kontrat test edilir.
"""

from __future__ import annotations

import pytest

from multimodal.ocr import OCRResult, extract_text


@pytest.mark.asyncio
async def test_extract_text_empty_bytes():
    r = await extract_text(b"")
    assert r.text == ""
    assert r.n_chars == 0
    assert r.error and "boş" in r.error.lower()


@pytest.mark.asyncio
async def test_extract_text_qwen_vl_disabled_returns_error(monkeypatch):
    monkeypatch.delenv("OCR_QWEN_VL_ENABLED", raising=False)
    # Geçersiz/dummy bytes ama qwen-vl explicit istek
    r = await extract_text(b"dummy", engine="qwen-vl")
    assert r.engine == "qwen-vl"
    assert r.error is not None
    assert "disabled" in r.error.lower() or "qwen-vl" in r.error.lower()


@pytest.mark.asyncio
async def test_extract_text_returns_ocr_result_shape():
    """Tesseract olmasa bile OCRResult şeması korunmalı (graceful)."""
    r = await extract_text(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # geçersiz PNG
    assert isinstance(r, OCRResult)
    assert hasattr(r, "text")
    assert hasattr(r, "engine")
    assert hasattr(r, "n_chars")
    assert hasattr(r, "elapsed_ms")
    # error VEYA text dolu olur — ikisi birden None olamaz
    assert r.text != "" or r.error is not None


@pytest.mark.asyncio
async def test_extract_text_invalid_image_returns_error_not_crash():
    """Bozuk image bytes → exception fırlatmamalı, error field set etmeli."""
    r = await extract_text(b"this-is-not-an-image-just-text")
    # Crashlamadı → şema hâlâ tutarlı
    assert isinstance(r, OCRResult)
    # Tesseract çıktısı boş veya error message
    assert r.n_chars == 0 or r.error is not None
