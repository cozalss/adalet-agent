"""OCR — belge fotoğraflarından metin çıkarımı.

İki seviyeli strateji:
  1. **Tesseract 5** (TR dil paketi) — hızlı, basılı metin, varsayılan
  2. **Qwen2-VL** (HF, opsiyonel) — el yazısı / kompleks / tablo için fallback

Türkçe karakterler `chunker.sanitize_text` ile NFC normalize edilir; Tesseract
çıkışındaki tipik mojibake (`Ã§` → `ç`) zaten orada düzeltilir → reuse.

PIL ile basit preprocess: grayscale + adaptive threshold (Otsu) kalite arttırır.

Gizlilik: TCKN/telefon/isim test verilerinde sahte (`12345678901`, `0555...`).

Kullanım:
    result = await extract_text(image_bytes, lang="tur")
    result.text     → "Madde 11 ..."
    result.engine   → "tesseract" | "qwen2-vl"
    result.elapsed_ms

ENV:
    OCR_ENGINE=tesseract|qwen-vl  (default tesseract)
    OCR_DPI=300                    (preprocess dpi target)
    OCR_TIMEOUT_S=30
"""

from __future__ import annotations

import asyncio
import io
import os
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import structlog

from retrieval.chunker import sanitize_text

log = structlog.get_logger()

# Qwen-VL model yükleme kilidi (#18): _load_qwen_vl `to_thread` içinde çağrılır;
# lru_cache thread-güvenli DEĞİL (eş zamanlı ilk-istek iki kez from_pretrained →
# çift ~5GB → OOM, LlamaCpp load-race ile aynı sınıf). _get_qwen_vl lock ile sarar.
_vl_load_lock = threading.Lock()


@lru_cache(maxsize=1)
def _load_qwen_vl(model_name: str) -> tuple[Any, Any]:
    """Qwen2-VL processor+model'i bir kez yükle, cache'le (~5GB).

    Önceki kod HER OCR isteğinde from_pretrained çağırıyordu → her çağrıda 5GB
    VRAM/RAM + deserialization → paralel isteklerde OOM. lru_cache(1) ile
    process ömrü boyunca tek yükleme (STT/TTS cached_property'sinin OCR karşılığı).
    Eş zamanlılık kilidi için _get_qwen_vl üzerinden çağır.
    """
    from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
    processor = AutoProcessor.from_pretrained(model_name)
    model = Qwen2VLForConditionalGeneration.from_pretrained(model_name)
    log.info("qwen_vl_loaded", model=model_name)
    return processor, model


def _get_qwen_vl(model_name: str) -> tuple[Any, Any]:
    """Kilit-korumalı Qwen-VL erişimi (#18): paralel ilk-istekte tek yükleme garantisi.
    Yüklendikten sonra lru_cache hit → kilit ucuz; yükleme sırasında 2. istek bekler."""
    with _vl_load_lock:
        return _load_qwen_vl(model_name)

OCREngine = Literal["tesseract", "qwen-vl", "auto"]

DEFAULT_ENGINE = os.getenv("OCR_ENGINE", "tesseract").lower()
OCR_TIMEOUT_S = float(os.getenv("OCR_TIMEOUT_S", "30"))
OCR_LANG = os.getenv("OCR_LANG", "tur")
MIN_TEXT_LEN_QWEN_FALLBACK = 50  # Tesseract bundan az çıkardıysa Qwen-VL dene

# Sprint-6: project-local tessdata path (tur.traineddata burada).
# Windows'da `C:\Program Files\Tesseract-OCR\tessdata` admin yetkisi gerek,
# bu yüzden backend/models/tessdata/ kullanıyoruz.
_LOCAL_TESSDATA = (__import__("pathlib").Path(__file__).parent.parent
                   / "models" / "tessdata")
if _LOCAL_TESSDATA.exists() and not os.getenv("TESSDATA_PREFIX"):
    os.environ["TESSDATA_PREFIX"] = str(_LOCAL_TESSDATA)

# Windows: tesseract.exe binary path (winget default install dizini).
# Import-time check — async fn içinde os.path.exists kullanmamak için
# (ruff ASYNC240). PATH'e ekli değilse pytesseract bulamaz, set ediyoruz.
_DEFAULT_TESSERACT_CMD_WIN = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_TESSERACT_CMD: str | None = (
    _DEFAULT_TESSERACT_CMD_WIN
    if os.name == "nt" and __import__("pathlib").Path(_DEFAULT_TESSERACT_CMD_WIN).exists()
    else None
)


@dataclass(slots=True)
class OCRResult:
    """OCR çıktısı + meta."""

    text: str
    engine: str
    lang: str
    n_chars: int
    elapsed_ms: int
    error: str | None = None
    # Ortalama word-confidence 0..1 (Tesseract image_to_data). Düşük = bozuk tarama/
    # el yazısı → istemci/ajan uyarılabilir (#20). Qwen-VL'de yok → None.
    confidence: float | None = None


# --------------------------------------------------------------------------
#  Public API
# --------------------------------------------------------------------------

async def extract_text(
    image_bytes: bytes,
    *,
    lang: str = OCR_LANG,
    engine: OCREngine = "auto",
) -> OCRResult:
    """Görüntüden metin çıkar.

    Args:
        image_bytes: PNG/JPG/PDF (single page) bytes
        lang: Tesseract dil kodu ("tur" tek; "tur+eng" çoklu)
        engine: "tesseract", "qwen-vl", veya "auto" (env default + fallback)
    """
    if not image_bytes:
        return OCRResult(
            text="", engine="none", lang=lang, n_chars=0, elapsed_ms=0,
            error="boş görüntü",
        )

    chosen = engine if engine != "auto" else DEFAULT_ENGINE
    start = time.perf_counter()

    if chosen == "qwen-vl":
        result = await _qwen_vl_ocr(image_bytes, lang)
    else:
        result = await _tesseract_ocr(image_bytes, lang)
        # Auto-mode: Tesseract zayıfsa Qwen-VL'a düş
        if (
            engine == "auto"
            and result.n_chars < MIN_TEXT_LEN_QWEN_FALLBACK
            and not result.error
        ):
            log.info("ocr_tesseract_weak_fallback_qwen", n_chars=result.n_chars)
            result = await _qwen_vl_ocr(image_bytes, lang)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return OCRResult(
        text=result.text,
        engine=result.engine,
        lang=lang,
        n_chars=len(result.text),
        elapsed_ms=elapsed_ms,
        error=result.error,
        confidence=result.confidence,
    )


# --------------------------------------------------------------------------
#  Tesseract 5 — basit, hızlı, default
# --------------------------------------------------------------------------

async def _tesseract_ocr(image_bytes: bytes, lang: str) -> OCRResult:
    """pytesseract subprocess wrapper. PIL preprocess + sanitize."""
    try:
        import pytesseract
        from PIL import Image, ImageOps
        Image.MAX_IMAGE_PIXELS = 50_000_000  # güvenlik: decompression-bomb guard (~A4 300dpi)
    except ImportError as exc:
        # Tam detay (lib adı/exc) sadece sunucu log'una; kullanıcıya generic.
        log.warning("ocr_tesseract_import_failed", error=str(exc))
        return OCRResult(
            text="", engine="tesseract", lang=lang, n_chars=0,
            elapsed_ms=0, error="OCR motoru kullanılamıyor",
        )

    if _TESSERACT_CMD is not None:
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD

    def _do() -> tuple[str, str | None, float | None]:
        try:
            img = Image.open(io.BytesIO(image_bytes))
            img = _preprocess(img, ImageOps)
            text = pytesseract.image_to_string(img, lang=lang, config="--oem 3 --psm 6")
            # Güven sinyali (#20): word-düzey conf (0-100; -1=non-text) ortalaması → 0..1.
            # Best-effort: başarısızsa metin yine döner (conf=None). Ayrı çağrı; OCR
            # latency-kritik değil (tek-seferlik upload, async, 30s timeout).
            conf: float | None = None
            try:
                from pytesseract import Output
                data = pytesseract.image_to_data(
                    img, lang=lang, config="--oem 3 --psm 6", output_type=Output.DICT,
                )
                vals = [int(c) for c in data.get("conf", [])
                        if str(c).lstrip("-").isdigit() and int(c) >= 0]
                if vals:
                    conf = round(sum(vals) / len(vals) / 100.0, 3)
            except Exception as exc:
                log.info("ocr_confidence_unavailable", error=str(exc))
            return sanitize_text(text), None, conf
        except Exception as exc:
            # exc dosya yolu/iç detay sızdırabilir → log'a, kullanıcıya generic.
            log.warning("ocr_tesseract_failed", error=str(exc))
            return "", "OCR işlenemedi", None

    try:
        text, err, conf = await asyncio.wait_for(asyncio.to_thread(_do), timeout=OCR_TIMEOUT_S)
    except TimeoutError:
        return OCRResult(
            text="", engine="tesseract", lang=lang, n_chars=0,
            elapsed_ms=int(OCR_TIMEOUT_S * 1000),
            error=f"tesseract timeout ({OCR_TIMEOUT_S}s)",
        )

    log.info("ocr_tesseract_done", lang=lang, n_chars=len(text), error=err, confidence=conf)
    return OCRResult(
        text=text, engine="tesseract", lang=lang, n_chars=len(text),
        elapsed_ms=0, error=err, confidence=conf,
    )


def _preprocess(img, ImageOps):  # noqa: N803
    """Grayscale + autocontrast — Tesseract için temel iyileştirme.

    Mevzuat tarama PDF'lerinde tipik düşük kontrast sorunlarını çözer.
    """
    if img.mode != "L":
        img = img.convert("L")
    img = ImageOps.autocontrast(img, cutoff=2)
    # Çok küçük image upscale → Tesseract DPI varsayımı 300
    w, h = img.size
    if max(w, h) < 1000:
        new_w = int(w * 2.0)
        new_h = int(h * 2.0)
        img = img.resize((new_w, new_h))
    return img


# --------------------------------------------------------------------------
#  Qwen2-VL — opsiyonel fallback (kompleks / el yazısı / tablo)
# --------------------------------------------------------------------------

async def _qwen_vl_ocr(image_bytes: bytes, lang: str) -> OCRResult:
    """Qwen2-VL-2B-Instruct — el yazısı/karmaşık layout için.

    Bu model ağır (~5GB indirme). Yüklemesi başarısızsa graceful fallback:
    Tesseract sonucunu (varsa) ya da boş OCRResult döner. Sprint-5 ilk
    iterasyonda ENV ile opt-in: `OCR_QWEN_VL_ENABLED=1` olmadıkça çağrılmaz.
    """
    if os.getenv("OCR_QWEN_VL_ENABLED", "0").lower() not in {"1", "true", "yes"}:
        return OCRResult(
            text="", engine="qwen-vl", lang=lang, n_chars=0,
            elapsed_ms=0,
            error="qwen-vl disabled (OCR_QWEN_VL_ENABLED=1 ile aç)",
        )

    # transformers kurulu mu? (isim bağlamadan probe — gerçek yükleme cache'li
    # _load_qwen_vl'de). Yoksa graceful fallback.
    import importlib.util
    if importlib.util.find_spec("transformers") is None:
        log.warning("ocr_qwen_import_failed", error="transformers not installed")
        return OCRResult(
            text="", engine="qwen-vl", lang=lang, n_chars=0,
            elapsed_ms=0, error="OCR motoru kullanılamıyor",
        )

    def _do() -> tuple[str, str | None]:
        try:
            from PIL import Image
            Image.MAX_IMAGE_PIXELS = 50_000_000  # güvenlik: decompression-bomb guard
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            model_name = os.getenv("OCR_QWEN_VL_MODEL", "Qwen/Qwen2-VL-2B-Instruct")
            # Cache'li + kilit-korumalı yükleme — process başına bir kez (OOM/race fix #18).
            processor, model = _get_qwen_vl(model_name)

            prompt = (
                "Aşağıdaki Türkçe hukuk belgesinin metnini AYNEN yaz. "
                "Hiçbir şey ekleme, çıkarma, yorumlama. Sadece görsel "
                "metin çıktısı:"
            )
            # Qwen2-VL ZORUNLU sözleşme (#16): görsel placeholder'lı chat template olmadan
            # vision token'ları enjekte edilmez → boş/çöp çıktı. Üretimden sonra input
            # token'larını DİLİMLE (yoksa batch_decode prompt'u da yankılar). (Context7/HF doc.)
            conversation = [{"role": "user", "content": [
                {"type": "image"}, {"type": "text", "text": prompt}]}]
            text_prompt = processor.apply_chat_template(
                conversation, tokenize=False, add_generation_prompt=True,
            )
            inputs = processor(text=[text_prompt], images=[img], return_tensors="pt")
            output_ids = model.generate(**inputs, max_new_tokens=2048)
            trimmed = [
                out[len(inp):] for inp, out in zip(inputs.input_ids, output_ids)
            ]
            text = processor.batch_decode(
                trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=True,
            )[0]
            return sanitize_text(text), None
        except Exception as exc:
            log.warning("ocr_qwen_failed", error=str(exc))
            return "", "OCR işlenemedi"

    try:
        text, err = await asyncio.wait_for(
            asyncio.to_thread(_do), timeout=OCR_TIMEOUT_S * 2,
        )
    except TimeoutError:
        return OCRResult(
            text="", engine="qwen-vl", lang=lang, n_chars=0,
            elapsed_ms=int(OCR_TIMEOUT_S * 2000),
            error="qwen-vl timeout",
        )

    log.info("ocr_qwen_vl_done", n_chars=len(text), error=err)
    return OCRResult(
        text=text, engine="qwen-vl", lang=lang, n_chars=len(text),
        elapsed_ms=0, error=err,
    )


__all__ = ("OCREngine", "OCRResult", "extract_text")
