"""OCR — belge (PDF/görsel) → metin çıkarımı.

Yönlendirme:
  • **PDF (dijital)** — gömülü metin katmanı varsa PyMuPDF ile doğrudan okunur
    (`pdf_utils.extract_pdf_text`): OCR'sız, **kusursuz Türkçe**. Hukuk
    belgelerinin çoğu (UYAP/e-Devlet, Word export) böyledir.
  • **PDF (taranmış) / görsel** — metin katmanı yoksa sayfalar görsele render
    edilip (`pdf_utils.render_pdf_to_images`) seçili motora verilir:
      1. **RapidOCR** (onnxruntime) — pip-tabanlı, offline, sistem-kurulumsuz; VARSAYILAN
      2. **Tesseract 5** (TR dil paketi) — tam Türkçe diakritik (binary gerekir)
      3. **Qwen2-VL** (HF, opt-in) — el yazısı / kompleks / tablo fallback

Türkçe karakterler `_normalize_ocr_text` (sanitize_text + NBSP) ile tüm
motorlarda tutarlı NFC normalize edilir.

Gizlilik: TCKN/telefon/isim test verilerinde sahte (`12345678901`, `0555...`).
Yüklenen içerik yalnız bellekte işlenir.

Kullanım:
    result = await extract_text(doc_bytes)        # engine="auto"
    result.text       → "Madde 11 ..."
    result.engine     → "pdf-text" | "rapidocr" | "pdf-scan-rapidocr" | ...
    result.page_count → çok-sayfa PDF'te sayfa sayısı

ENV:
    OCR_ENGINE=rapidocr|tesseract|qwen-vl  (default rapidocr)
    OCR_TIMEOUT_S=30                        (motor başına / PDF adımı başına)
    OCR_PDF_MAX_PAGES=10                    (DoS/latency guard)
    OCR_PDF_DPI=200                         (tarama render çözünürlüğü)
    OCR_RAPIDOCR_REC_MODEL / OCR_RAPIDOCR_KEYS  (Latin model — tam diakritik)
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

from multimodal.ocr_rapidocr import rapidocr_image
from multimodal.pdf_utils import extract_pdf_text, is_pdf, render_pdf_to_images
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

OCREngine = Literal["tesseract", "rapidocr", "qwen-vl", "auto"]

# Varsayılan görsel-OCR motoru. RapidOCR pip-tabanlı + offline çalışır (sistem
# tesseract.exe kurulumu GEREKMEZ) → kutudan çıkar çıkmaz çalışır. Tesseract'a
# OCR_ENGINE=tesseract ile geçilebilir (tam Türkçe diakritik, binary gerekir).
DEFAULT_ENGINE = os.getenv("OCR_ENGINE", "rapidocr").lower()
OCR_TIMEOUT_S = float(os.getenv("OCR_TIMEOUT_S", "30"))
OCR_LANG = os.getenv("OCR_LANG", "tur")
MIN_TEXT_LEN_QWEN_FALLBACK = 50  # Görsel motoru bundan az çıkardıysa Qwen-VL dene (opt-in)
# Dijital PDF'te bu kadar gömülü metin varsa "metin katmanı var" sayılır → OCR'a
# gerek yok (kusursuz + Türkçe-diakritikli). Altındaysa taranmış → render+OCR.
PDF_TEXT_MIN_CHARS = int(os.getenv("OCR_PDF_TEXT_MIN_CHARS", "20"))

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


def _normalize_ocr_text(text: str) -> str:
    """OCR/PDF çıktısını temizle: NFC + mojibake (sanitize_text) + PDF tipik
    kırılmaz-boşluk (\\xa0) → boşluk. Tüm motorlarda tutarlı metin garantisi."""
    if not text:
        return text
    return sanitize_text(text.replace("\xa0", " "))


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
    # PDF sayfa sayısı (görselde 1). Çok-sayfa belgede istemci "3 sayfa işlendi"
    # gösterebilir; sayfa-cap aşıldıysa kullanıcı eksik metni anlar.
    page_count: int = 1


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
        image_bytes: PNG/JPG/WEBP/TIFF veya PDF (çok-sayfa; OCR_PDF_MAX_PAGES'e kadar)
        lang: Tesseract dil kodu ("tur" tek; "tur+eng" çoklu)
        engine: "rapidocr", "tesseract", "qwen-vl", veya "auto" (env default + fallback)
    """
    if not image_bytes:
        return OCRResult(
            text="", engine="none", lang=lang, n_chars=0, elapsed_ms=0,
            error="boş görüntü",
        )

    chosen = engine if engine != "auto" else DEFAULT_ENGINE
    auto = engine == "auto"
    start = time.perf_counter()

    # PDF? → önce dijital metin katmanı (kusursuz Türkçe), yoksa render+OCR (tarama).
    if is_pdf(image_bytes):
        result = await _pdf_ocr(image_bytes, lang, chosen, auto=auto)
    else:
        result = await _image_ocr(image_bytes, lang, chosen, auto=auto)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return OCRResult(
        text=result.text,
        engine=result.engine,
        lang=lang,
        n_chars=len(result.text),
        elapsed_ms=elapsed_ms,
        error=result.error,
        confidence=result.confidence,
        page_count=result.page_count,
    )


async def _image_ocr(
    image_bytes: bytes, lang: str, chosen: str, *, auto: bool,
) -> OCRResult:
    """Tek görüntüyü seçili motorla OCR'la (+ auto modda zayıf→Qwen-VL fallback)."""
    if chosen == "qwen-vl":
        return await _qwen_vl_ocr(image_bytes, lang)
    if chosen == "tesseract":
        result = await _tesseract_ocr(image_bytes, lang)
    else:  # "rapidocr" (varsayılan) ve tanınmayan değerler
        result = await _rapidocr_ocr(image_bytes, lang)

    # Auto-mode: birincil motor zayıf çıktı verdiyse (kısa metin) Qwen-VL dene.
    # Yalnız Qwen DAHA FAZLA metin döndürürse benimse — disabled/boş fallback
    # geçerli-ama-kısa sonucu EZMESİN (regresyon guard).
    if auto and result.n_chars < MIN_TEXT_LEN_QWEN_FALLBACK and not result.error:
        log.info("ocr_weak_fallback_qwen", primary=result.engine, n_chars=result.n_chars)
        fallback = await _qwen_vl_ocr(image_bytes, lang)
        if not fallback.error and fallback.n_chars > result.n_chars:
            return fallback
    return result


async def _pdf_ocr(
    pdf_bytes: bytes, lang: str, chosen: str, *, auto: bool,
) -> OCRResult:
    """PDF → metin. Dijital metin katmanı varsa onu kullan (OCR'sız, kusursuz);
    yoksa sayfaları görsele render edip OCR'la (taranmış belge)."""
    # PyMuPDF parse/render bloklayıcı + kötücül PDF'te uzun sürebilir → OCR
    # motorlarıyla simetrik olarak timeout-korumalı (event loop'u bekletme).
    try:
        text, page_count = await asyncio.wait_for(
            asyncio.to_thread(extract_pdf_text, pdf_bytes), timeout=OCR_TIMEOUT_S,
        )
    except TimeoutError:
        return OCRResult(
            text="", engine="pdf-text", lang=lang, n_chars=0,
            elapsed_ms=int(OCR_TIMEOUT_S * 1000),
            error="PDF işleme zaman aşımı", page_count=1,
        )
    text = _normalize_ocr_text(text)
    if len(text) >= PDF_TEXT_MIN_CHARS:
        log.info("pdf_digital_text", n_chars=len(text), pages=page_count)
        return OCRResult(
            text=text, engine="pdf-text", lang=lang, n_chars=len(text),
            elapsed_ms=0, confidence=None, page_count=page_count,
        )

    # Metin katmanı yok/yetersiz → taranmış. Sayfaları render et + OCR.
    try:
        images = await asyncio.wait_for(
            asyncio.to_thread(render_pdf_to_images, pdf_bytes), timeout=OCR_TIMEOUT_S,
        )
    except TimeoutError:
        return OCRResult(
            text="", engine="pdf-text", lang=lang, n_chars=0,
            elapsed_ms=int(OCR_TIMEOUT_S * 1000),
            error="PDF render zaman aşımı", page_count=page_count,
        )
    if not images:
        return OCRResult(
            text="", engine="pdf-text", lang=lang, n_chars=0, elapsed_ms=0,
            error="PDF'den metin çıkarılamadı (şifreli veya bozuk olabilir)",
            page_count=page_count,
        )

    # Kümülatif deadline: N sayfa × per-sayfa timeout, isteğin saatlerce
    # sürüp thread-pool'u doldurmasını önler (rate-limit istek SAYISINI sınırlar,
    # SÜRESİNİ değil → ek savunma).
    loop = asyncio.get_running_loop()  # _pdf_ocr async; get_event_loop() 3.12'de deprecated
    deadline = loop.time() + OCR_TIMEOUT_S * len(images)
    page_texts: list[str] = []
    confs: list[float] = []
    last_error: str | None = None
    pages_failed = 0
    for idx, page_png in enumerate(images):
        remaining = deadline - loop.time()
        if remaining <= 0:
            last_error = "taranmış belge çok uzun (zaman aşımı)"
            log.warning("pdf_scan_deadline_exceeded", processed=idx, total=len(images))
            break
        try:
            r = await asyncio.wait_for(
                _image_ocr(page_png, lang, chosen, auto=auto), timeout=remaining,
            )
        except TimeoutError:
            pages_failed += 1
            last_error = "sayfa OCR zaman aşımı"
            log.warning("pdf_page_ocr_timeout", page=idx)
            continue
        if r.text:
            page_texts.append(r.text)
        if r.confidence is not None:
            confs.append(r.confidence)
        if r.error:
            pages_failed += 1
            last_error = r.error
            log.warning("pdf_page_ocr_failed", page=idx, error=r.error)
    combined = "\n\n".join(page_texts).strip()
    # "auto" bu noktada çözülmüş; chosen gerçek motor → doğru etiket.
    img_engine = chosen if chosen in {"tesseract", "qwen-vl", "rapidocr"} else "rapidocr"
    if pages_failed:
        log.info("pdf_scan_partial", pages_failed=pages_failed, total=len(images))
    return OCRResult(
        text=combined,
        engine=f"pdf-scan-{img_engine}",
        lang=lang,
        n_chars=len(combined),
        elapsed_ms=0,
        error=None if combined else (last_error or "Taranmış PDF'den metin okunamadı"),
        confidence=round(sum(confs) / len(confs), 3) if confs else None,
        page_count=page_count,
    )


# --------------------------------------------------------------------------
#  RapidOCR — pip-tabanlı, offline, sistem-kurulumsuz (varsayılan görsel motoru)
# --------------------------------------------------------------------------

async def _rapidocr_ocr(image_bytes: bytes, lang: str) -> OCRResult:
    """RapidOCR (onnxruntime) — timeout-korumalı async wrapper."""
    try:
        text, conf, err = await asyncio.wait_for(
            asyncio.to_thread(rapidocr_image, image_bytes), timeout=OCR_TIMEOUT_S,
        )
    except TimeoutError:
        return OCRResult(
            text="", engine="rapidocr", lang=lang, n_chars=0,
            elapsed_ms=int(OCR_TIMEOUT_S * 1000),
            error="OCR zaman aşımı",
        )
    text = _normalize_ocr_text(text)
    log.info("ocr_rapidocr_done", lang=lang, n_chars=len(text), error=err, confidence=conf)
    return OCRResult(
        text=text, engine="rapidocr", lang=lang, n_chars=len(text),
        elapsed_ms=0, error=err, confidence=conf,
    )


# --------------------------------------------------------------------------
#  Tesseract 5 — basit, hızlı; tam Türkçe diakritik (binary gerekir)
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
            error="OCR zaman aşımı",
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
        # İç ENV değişken adını istemciye sızdırma; detay log tarafında.
        log.info("ocr_qwen_vl_disabled")
        return OCRResult(
            text="", engine="qwen-vl", lang=lang, n_chars=0,
            elapsed_ms=0,
            error="qwen-vl motoru aktif değil",
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
