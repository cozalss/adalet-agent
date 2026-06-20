"""RapidOCR motoru — pip-tabanlı, offline, sistem-kurulumsuz OCR (onnxruntime).

Tesseract'ın aksine **sistem binary'si gerekmez** (tesseract.exe + admin yetkisi
yok): modeller wheel ile gelir, ilk çağrıda yüklenir. Taranmış belge / fotoğraf
yolu için varsayılan motor.

Türkçe diakritik notu: paket varsayılan tanıma modeli (PP-OCRv4 ch+en) Latin
harflerini okur ama Türkçe'ye özel ç/ş/ğ/ı/ö/ü işaretlerini **düşürebilir**
("İşçi" → "isci"). Tam diakritik için Latin tanıma modeli ENV ile takılabilir:
    OCR_RAPIDOCR_REC_MODEL=/yol/latin_rec.onnx
    OCR_RAPIDOCR_KEYS=/yol/latin_keys.txt
Model verilmezse varsayılan (diakritiksiz ama okunur) çıktıyla çalışır.

Dijital PDF metni (pdf_utils.extract_pdf_text) bu kısıttan etkilenmez — Türkçe
karakterleri kusursuz korur; OCR yalnız metin katmanı olmayan taramalar içindir.
"""

from __future__ import annotations

import io
import os
import threading
from functools import lru_cache
from typing import Any

import structlog

log = structlog.get_logger()

# RapidOCR() ~3 onnx modeli yükler (~0.86s) — Qwen-VL ile aynı sınıf race riski:
# eş zamanlı ilk-istek iki kez yükler. lru_cache(1) + lock ile process başına tek.
_engine_lock = threading.Lock()


@lru_cache(maxsize=1)
def _load_engine() -> Any:
    """RapidOCR örneğini bir kez kur, cache'le. ENV ile Latin model opsiyonel."""
    from rapidocr_onnxruntime import RapidOCR

    kwargs: dict[str, str] = {}
    rec_model = os.getenv("OCR_RAPIDOCR_REC_MODEL")
    rec_keys = os.getenv("OCR_RAPIDOCR_KEYS")
    if rec_model and rec_keys:
        # Latin tanıma modeli takılıysa tam Türkçe diakritik desteği.
        kwargs = {"Rec.model_path": rec_model, "Rec.keys_path": rec_keys}
        log.info("rapidocr_custom_rec_model", model=rec_model)
    engine = RapidOCR(**kwargs) if kwargs else RapidOCR()
    log.info("rapidocr_loaded")
    return engine


def _get_engine() -> Any:
    """Kilit-korumalı RapidOCR erişimi (paralel ilk-istekte tek yükleme garantisi)."""
    with _engine_lock:
        return _load_engine()


def rapidocr_image(image_bytes: bytes) -> tuple[str, float | None, str | None]:
    """Görüntü byte'larından metin çıkar (senkron — to_thread içinden çağır).

    Returns:
        (text, confidence, error). confidence = satır-skoru ortalaması 0..1.
        Motor kurulu değilse veya hata olursa ("", None, mesaj).
    """
    try:
        import numpy as np
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = 50_000_000  # decompression-bomb guard
    except ImportError as exc:
        log.warning("rapidocr_dep_missing", error=str(exc))
        return "", None, "OCR motoru kullanılamıyor"

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        engine = _get_engine()
        result, _elapse = engine(arr)
    except Exception as exc:
        # İç detay (yol/model) sızdırabilir → log'a, çağırana generic.
        log.warning("rapidocr_failed", error=str(exc))
        return "", None, "OCR işlenemedi"

    if not result:
        return "", None, None  # metin bulunamadı (boş belge) — hata değil

    # RapidOCR: [[box, text, score], ...]. Metni birleştir, skor ortalamasını al.
    # Güven düşükse text alanı None gelebilir → str(None)="None" çöpünü engelle.
    lines = [str(line[1]) for line in result if len(line) > 1 and line[1] is not None]
    scores = [float(line[2]) for line in result if len(line) > 2]
    text = "\n".join(lines)
    confidence = round(sum(scores) / len(scores), 3) if scores else None
    return text, confidence, None


__all__ = ("rapidocr_image",)
