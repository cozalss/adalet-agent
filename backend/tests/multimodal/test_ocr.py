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


@pytest.mark.asyncio
async def test_qwen_vl_uses_chat_template_and_trims_output(monkeypatch):
    """Denetim #16: Qwen2-VL görsel-placeholder'lı apply_chat_template kullanmalı (yoksa
    vision token enjekte edilmez → boş çıktı) + üretimden sonra input token'larını dilimlemeli
    (yoksa batch_decode prompt'u yankılar)."""
    import io as _io

    pytest.importorskip("PIL")

    from PIL import Image

    import multimodal.ocr as ocr

    buf = _io.BytesIO()
    Image.new("RGB", (4, 4), (255, 255, 255)).save(buf, format="PNG")
    png = buf.getvalue()

    calls: dict = {}

    class FakeInputs(dict):
        @property
        def input_ids(self):
            return self["input_ids"]

    class FakeProcessor:
        def apply_chat_template(self, conversation, tokenize=False, add_generation_prompt=False):
            calls["template"] = conversation
            return "<vision>PROMPT"

        def __call__(self, text=None, images=None, return_tensors=None):
            calls["images"] = images
            return FakeInputs(input_ids=[[1, 2, 3]], attention_mask=[[1, 1, 1]])

        def batch_decode(self, ids, skip_special_tokens=True, clean_up_tokenization_spaces=True):
            calls["decoded_ids"] = ids
            return ["Madde 11 metni"]

    class FakeModel:
        def generate(self, **kwargs):
            return [[1, 2, 3, 9, 9]]  # input(3) + generated(2)

    monkeypatch.setattr(ocr, "_get_qwen_vl", lambda *_a: (FakeProcessor(), FakeModel()))
    monkeypatch.setattr("importlib.util.find_spec", lambda *_a: object())
    monkeypatch.setenv("OCR_QWEN_VL_ENABLED", "1")

    r = await ocr.extract_text(png, engine="qwen-vl")

    assert r.error is None
    assert "Madde 11" in r.text
    # chat template HEM image HEM text içerik taşıdı (vision placeholder şart)
    content_types = {c["type"] for c in calls["template"][0]["content"]}
    assert content_types == {"image", "text"}
    assert calls["images"]  # görsel processor'a verildi
    # batch_decode TRİMLENMİŞ id aldı (prompt echo değil): [[9, 9]]
    assert calls["decoded_ids"] == [[9, 9]]


def test_get_qwen_vl_holds_lock_during_load(monkeypatch):
    """Denetim #18: model yükleme kilit altında olmalı (paralel ilk-istek çift 5GB OOM önle)."""
    import multimodal.ocr as ocr

    seen: dict = {}

    def fake_load(name):
        seen["locked_during_load"] = ocr._vl_load_lock.locked()
        return ("proc", "model")

    monkeypatch.setattr(ocr, "_load_qwen_vl", fake_load)
    result = ocr._get_qwen_vl("any-model")

    assert result == ("proc", "model")
    assert seen["locked_during_load"] is True       # yükleme kilit altında çalıştı
    assert ocr._vl_load_lock.locked() is False       # sonra serbest bırakıldı
