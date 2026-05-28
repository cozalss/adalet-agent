"""Dilekçe renderer — jinja2 markdown + reportlab PDF.

İki aşama:
    1. Jinja2 ile DilekceContext → markdown string (deterministic, LLM yok)
    2. Markdown → reportlab PDF bytes (Türkçe karakterler için Helvetica yerine
       reportlab'ın yerleşik 'STSong-Light' alternatifi kabul edilemez; sistemde
       bulunmayan DejaVuSans yerine reportlab built-in Helvetica varyantı +
       UTF-8 string encoding kullanılır)

Mimari (architect kararı):
    - PDF in-memory bytes; state'e yazılır, API endpoint stream eder
    - Disk persistence yok (KVKK + test kolaylığı)
    - Sıfır halüsinasyon: yalnız VERIFIED içerik + KAYNAKLI Citation interpolation

Türkçe karakter desteği:
    reportlab Helvetica WinAnsiEncoding ile ç ş ğ İ vb. düzgün render eder
    (1.x'ten beri). Custom TTF embed gerekirse `_register_dejavu()` çağırılır.
"""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from agents.config import DILEKCE_MAX_PDF_BYTES
from agents.dilekce.models import DilekceContext, DilekceResult
from agents.dilekce.template_registry import template_label
from agents.state import Citation, Domain

log = structlog.get_logger()

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Jinja env — autoescape KAPALI (PDF markdown çıkar, HTML değil); StrictUndefined
# undefined değişkeni hata olarak verir (test'te kaçırılan placeholder yakalanır).
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

# Reportlab paragraph stilleri — başlık/normal/küçük. Helvetica WinAnsi
# Türkçe ç ş ğ ı İ Ö Ü karakterlerini doğru gösterir.
_styles = getSampleStyleSheet()
_h1 = ParagraphStyle(
    "H1", parent=_styles["Heading1"], fontSize=16, leading=20, spaceAfter=10,
)
_h2 = ParagraphStyle(
    "H2", parent=_styles["Heading2"], fontSize=12, leading=16, spaceAfter=6,
)
_body = ParagraphStyle(
    "Body", parent=_styles["BodyText"], fontSize=10, leading=14, spaceAfter=4,
)
_small = ParagraphStyle(
    "Small", parent=_styles["BodyText"], fontSize=8, leading=10, textColor="#666666",
)

# Markdown → reportlab basit dönüşüm (table/image YOK — dilekçe metin tabanlı).
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
_LI_RE = re.compile(r"^[-*]\s+(.+)$")
_NUM_LI_RE = re.compile(r"^(\d+)\.\s+(.+)$")
_HR_RE = re.compile(r"^---+\s*$")

# Bold ve italic - reportlab Paragraph XML-like markup (<b>, <i>) destekler.
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def _mark_to_xml(text: str) -> str:
    """**bold** ve *italic* markdown → reportlab <b>/<i> XML.

    Güvenlik: kullanıcı girdisi PDF metnine sızabilir (verified claim, case
    facts, user_meta). Sentinel/null-byte yaklaşımı kırılgandı (crafted input
    "<b>injected" ile reportlab Paragraph'a ham etiket sızdırabilirdi).
    Yeni yaklaşım: ÖNCE tüm XML-special karakterleri kaç, SONRA escape edilmiş
    `**` ve `*` pattern'larına bold/italic uygulanır.
    """
    # 1) Tüm metni XML-safe yap (kullanıcı girdisindeki <, > zararsız hâle gelir)
    escaped = (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
    # 2) Markdown sentaksı orijinal asterisk'ler korunmuş; escape edilmiş metinde
    #    "*..*" ve "**..**" hâlâ literal — bold/italic uygula.
    escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _ITALIC_RE.sub(r"<i>\1</i>", escaped)
    return escaped


def _render_markdown(ctx: DilekceContext) -> str:
    """Jinja → markdown string. Template-side LLM çağrısı yok."""
    template = _env.get_template(f"{ctx.template_id}.j2")
    return template.render(
        # Context fields
        soru=ctx.soru,
        olgular=ctx.olgular,
        hukuki_dayanak=ctx.hukuki_dayanak,
        emsal_destek=ctx.emsal_destek,
        ozet_metin=ctx.ozet_metin,
        tarih=ctx.tarih,
        user_meta=ctx.user_meta,
        # Optional override-able blocks (templates default'a düşer)
        karsi_taraf=ctx.user_meta.get("karsi_taraf", ""),
        talep_metni="",
    )


def _markdown_to_paragraphs(md: str) -> list[Paragraph | Spacer]:
    """Basit satır-bazlı markdown → reportlab Paragraph listesi.

    Desteklenen: # H1, ## H2, ### H3, **bold**, *italic*, - bullet, 1. ordered,
    --- hr (Spacer). Code block, table, image YOK (dilekçede gereksiz).
    """
    flowables: list[Paragraph | Spacer] = []
    for raw_line in md.splitlines():
        line = raw_line.rstrip()
        if not line:
            flowables.append(Spacer(1, 0.2 * cm))
            continue
        if _HR_RE.match(line):
            flowables.append(Spacer(1, 0.4 * cm))
            continue
        m_heading = _HEADING_RE.match(line)
        if m_heading:
            level = len(m_heading.group(1))
            text = _mark_to_xml(m_heading.group(2))
            style = _h1 if level == 1 else (_h2 if level == 2 else _body)
            flowables.append(Paragraph(text, style))
            continue
        m_li = _LI_RE.match(line)
        if m_li:
            flowables.append(Paragraph(f"&bull; {_mark_to_xml(m_li.group(1))}", _body))
            continue
        m_num = _NUM_LI_RE.match(line)
        if m_num:
            flowables.append(
                Paragraph(f"{m_num.group(1)}. {_mark_to_xml(m_num.group(2))}", _body),
            )
            continue
        if line.startswith("> "):
            flowables.append(Paragraph(_mark_to_xml(line[2:]), _small))
            continue
        flowables.append(Paragraph(_mark_to_xml(line), _body))
    return flowables


def _build_pdf(markdown: str, title: str) -> bytes:
    """Markdown → A4 PDF bytes. Disk yazımı YOK (in-memory BytesIO)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=title, author="ADALET-AGENT",
    )
    doc.build(_markdown_to_paragraphs(markdown))
    pdf_bytes = buf.getvalue()
    buf.close()
    if len(pdf_bytes) > DILEKCE_MAX_PDF_BYTES:
        raise ValueError(
            f"PDF too large: {len(pdf_bytes)} > {DILEKCE_MAX_PDF_BYTES} bytes",
        )
    return pdf_bytes


def _safe_filename(template_id: str, tarih: str) -> str:
    """Content-Disposition için güvenli dosya adı (yalnız ASCII + tire)."""
    base = template_id.replace("/", "-")
    # Türkçe karakter ASCII'ye düşür (HTTP header safety)
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    base = base.translate(tr_map)
    base = re.sub(r"[^A-Za-z0-9_-]", "-", base)
    return f"dilekce-{base}-{tarih}.pdf"


def render_dilekce(
    *,
    domain: Domain,
    template_id: str,
    soru: str,
    olgular: list[str],
    hukuki_dayanak: list[Citation],
    emsal_destek: list[Citation],
    ozet_metin: str,
    user_meta: dict[str, str] | None = None,
    tarih: str | None = None,
) -> DilekceResult:
    """Tek-çağrı render: DilekceContext kur → markdown → PDF bytes.

    Caller (dilekce_node) yalnız bu fonksiyona girer. Tüm exception'lar
    yukarı taşar (TemplateNotFound, UndefinedError, ValueError için size cap).

    KVKK: user_meta'da eksik anahtarlar template'lerde "[AD SOYAD]" gibi
    placeholder olarak kalır — gerçek TC/telefon ÜRETİLMEZ.
    """
    ctx = DilekceContext(
        domain=domain,
        template_id=template_id,
        soru=soru,
        olgular=olgular,
        hukuki_dayanak=hukuki_dayanak,
        emsal_destek=emsal_destek,
        ozet_metin=ozet_metin,
        tarih=tarih or date.today().isoformat(),
        user_meta=user_meta or {},
    )
    markdown = _render_markdown(ctx)
    title = template_label(template_id)
    pdf_bytes = _build_pdf(markdown, title)
    filename = _safe_filename(template_id, ctx.tarih)
    log.info(
        "dilekce_rendered",
        template_id=template_id, domain=domain,
        n_dayanak=len(hukuki_dayanak), n_emsal=len(emsal_destek),
        pdf_bytes=len(pdf_bytes),
    )
    return DilekceResult(
        template_id=template_id,
        markdown=markdown,
        pdf_bytes=pdf_bytes,
        filename=filename,
        n_dayanak=len(hukuki_dayanak),
        n_emsal=len(emsal_destek),
    )


__all__ = ("render_dilekce",)
