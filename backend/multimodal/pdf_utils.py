"""PDF yardımcıları — PyMuPDF (fitz) ile dijital metin + tarama render.

Hukuk belgelerinin çoğu **dijital PDF**'tir (UYAP/e-Devlet kararları, Word'den
export sözleşmeler, dilekçeler): gömülü metin katmanı vardır → OCR'a HİÇ gerek
yok, `extract_pdf_text` ile kusursuz + Türkçe-diakritikli metin alınır.

Yalnız **taranmış** PDF'lerde (fotokopi/scan, metin katmanı yok) sayfalar
görsele render edilip (`render_pdf_to_images`) OCR motoruna verilir.

Gizlilik: PDF içeriği yalnız bellekte işlenir; diske yazılmaz.

ENV:
    OCR_PDF_MAX_PAGES=10   — DoS/latency guard: bu kadar sayfa işlenir
    OCR_PDF_DPI=200        — tarama render çözünürlüğü (yüksek=daha iyi OCR, yavaş)
"""

from __future__ import annotations

import os

import structlog

log = structlog.get_logger()

# Tarama PDF'inde işlenecek azami sayfa (DoS/latency guard; 20MB upload sınırıyla
# birlikte ikinci savunma). Dijital metin çıkarımı da bu sınıra uyar.
MAX_PDF_PAGES = int(os.getenv("OCR_PDF_MAX_PAGES", "10"))
# Tarama sayfasını görsele çevirirken hedef DPI. 200 = OCR için yeterli/hızlı denge.
PDF_RENDER_DPI = int(os.getenv("OCR_PDF_DPI", "200"))
# GÜVENLİK (pixmap bellek bombası): kötücül PDF küçük dosyada DEVASA MediaBox
# bildirebilir (örn. 20000pt²) → get_pixmap GB'larca RAM ayırır → OOM. 20MB upload
# sınırı bunu engellemez (boş ama büyük sayfa <1KB olabilir). Render öncesi tahmini
# piksel sayısını sınırla (PIL decompression-bomb guard'ı ile aynı eşik).
MAX_RENDER_PIXELS = int(os.getenv("OCR_PDF_MAX_PIXELS", str(40_000_000)))


def is_pdf(data: bytes) -> bool:
    """İlk byte'lardan PDF imzası (`%PDF-`) tespit et."""
    return len(data) >= 5 and data[:5] == b"%PDF-"


def extract_pdf_text(data: bytes, *, max_pages: int = MAX_PDF_PAGES) -> tuple[str, int]:
    """Dijital PDF'in gömülü metin katmanını çıkar.

    Returns:
        (text, page_count). Metin katmanı yoksa (taranmış) text="" döner —
        çağıran bu durumda render+OCR yoluna düşer.

    Raises:
        İçeride yakalanır; bozuk/şifreli PDF'te ("", 0) döner (graceful).
    """
    import fitz  # PyMuPDF

    parts: list[str] = []
    page_count = 0
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:  # şifreli PDF — metin çıkarılamaz
                # page_count'u sızdırma (erişilemeyen belgenin metadata'sı) → 0.
                log.info("pdf_encrypted")
                return "", 0
            page_count = doc.page_count
            for idx, page in enumerate(doc):
                if idx >= max_pages:
                    log.info("pdf_text_page_cap", capped_at=max_pages, total=page_count)
                    break
                parts.append(page.get_text("text"))
    except Exception as exc:
        # Bozuk PDF içeriği iç detay sızdırabilir → log'a, çağırana boş.
        log.warning("pdf_text_extract_failed", error=str(exc))
        return "", page_count
    return "\n".join(parts).strip(), page_count


def render_pdf_to_images(
    data: bytes, *, max_pages: int = MAX_PDF_PAGES, dpi: int = PDF_RENDER_DPI,
) -> list[bytes]:
    """Taranmış PDF sayfalarını PNG byte'larına render et (OCR girdisi).

    Returns:
        Sayfa başına PNG bytes listesi (azami `max_pages`). Bozuk PDF'te [].
    """
    import fitz  # PyMuPDF

    images: list[bytes] = []
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                return []
            for idx, page in enumerate(doc):
                if idx >= max_pages:
                    break
                # GÜVENLİK: render öncesi tahmini piksel sayısı (MediaBox * dpi).
                # Devasa sayfayı render ETMEDEN atla → OOM guard.
                rect = page.rect
                est_px = (rect.width / 72 * dpi) * (rect.height / 72 * dpi)
                if est_px > MAX_RENDER_PIXELS:
                    log.warning(
                        "pdf_page_too_large", idx=idx,
                        width_pt=round(rect.width), height_pt=round(rect.height),
                        est_pixels=int(est_px),
                    )
                    continue
                pix = page.get_pixmap(dpi=dpi)
                # Defense-in-depth: gerçek piksel sayısını da doğrula (tahmin sapması).
                if pix.width * pix.height > MAX_RENDER_PIXELS:
                    log.warning("pdf_pixmap_too_large", idx=idx, w=pix.width, h=pix.height)
                    continue
                images.append(pix.tobytes("png"))
    except Exception as exc:
        log.warning("pdf_render_failed", error=str(exc))
        return []
    return images


__all__ = (
    "MAX_PDF_PAGES", "MAX_RENDER_PIXELS", "PDF_RENDER_DPI",
    "extract_pdf_text", "is_pdf", "render_pdf_to_images",
)
