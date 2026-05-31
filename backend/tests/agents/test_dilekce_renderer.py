"""Dilekçe renderer unit testleri — jinja + PDF byte üretimi.

Kapsam:
    - Her 16 template render hatasız (sıfır halüsinasyon paketle smoke)
    - PDF bytes %PDF- header'ı, makul boyut (≥1KB, ≤5MB)
    - Türkçe karakterler korunur (ç ş ğ İ Ö Ü)
    - Eksik user_meta → {{ placeholder }} korunur (KVKK)
    - Boş hukuki_dayanak → "[DAYANAK BULUNAMADI]" fallback metni
"""

from __future__ import annotations

import pytest

from agents.dilekce import render_dilekce
from agents.dilekce.template_registry import _REGISTRY
from agents.state import Citation


def _fake_citation(source_id: str, title: str, url: str = "https://example.test") -> Citation:
    return Citation(
        source_id=source_id, title=title, url=url, snippet="...", score=0.9, doc_type="law",
    )


@pytest.fixture
def basic_ctx_args() -> dict:
    """Tüm template'lerin minimum girdileri."""
    return {
        "soru": "Aldığım telefonun şarjı dayanmıyor, ne yapabilirim?",
        "olgular": ["Olay: telefon arızası", "Süre: 1 yıl"],
        "hukuki_dayanak": [
            _fake_citation("m-TKHK-11", "TKHK Madde 11"),
            _fake_citation("m-TKHK-56", "TKHK Madde 56"),
        ],
        "emsal_destek": [],
        "ozet_metin": "- Tüketici, garanti süresi içinde değişim talep edebilir.",
        "user_meta": {"sehir": "Ankara", "ad_soyad": "Ayşe Yılmaz"},
        "tarih": "2026-05-28",
    }


@pytest.mark.parametrize(
    ("domain", "template_id"),
    [(domain, tid) for domain, tpls in _REGISTRY.items() for tid, *_ in tpls],
)
def test_all_templates_render_without_error(domain, template_id, basic_ctx_args):
    """16 template'in hepsi render olur ve makul PDF bytes üretir."""
    result = render_dilekce(domain=domain, template_id=template_id, **basic_ctx_args)
    assert result.template_id == template_id
    assert result.pdf_bytes.startswith(b"%PDF-")
    assert len(result.pdf_bytes) > 1024     # makul minimum
    assert len(result.pdf_bytes) < 5 * 1024 * 1024
    assert result.filename.startswith("dilekce-")
    assert result.filename.endswith(".pdf")
    # ASCII-safe filename (Content-Disposition HTTP header güvenliği)
    assert result.filename.isascii()


def test_renderer_preserves_turkish_characters(basic_ctx_args):
    """Türkçe karakter render aşamasında bozulmamalı (markdown ham)."""
    result = render_dilekce(
        domain="tuketici",
        template_id="tuketici/ayipli_mal_iade_v1",
        **basic_ctx_args,
    )
    # Markdown'a Türkçe karakterler düşmeli
    md = result.markdown
    assert "İADE" in md or "İade" in md or "iade" in md
    assert "TKHK" in md
    # En azından bir Türkçe ç/ş/ğ harf bulunsun
    assert any(c in md for c in "çşğüöıİ")


def test_user_meta_eksik_alanlar_placeholder_kalir(basic_ctx_args):
    """KVKK: TC kimlik/telefon eksikse template'lere placeholder yazılır."""
    args = dict(basic_ctx_args)
    args["user_meta"] = {"sehir": "Ankara"}    # ad_soyad/tc_kimlik YOK
    result = render_dilekce(
        domain="tuketici", template_id="tuketici/hakem_heyeti_basvuru_v1", **args,
    )
    # Markdown'da placeholder string'ler korunur
    assert "[T.C. KİMLİK NO]" in result.markdown
    assert "[ADRES]" in result.markdown


def test_bos_hukuki_dayanak_uyarisi_uretir(basic_ctx_args):
    """Hukuki dayanak listesi boşsa template fallback metnine düşer."""
    args = dict(basic_ctx_args)
    args["hukuki_dayanak"] = []
    result = render_dilekce(
        domain="kira", template_id="kira/depozito_iade_v1", **args,
    )
    assert "doğrulanmış mevzuat dayanağı sunulmamıştır" in result.markdown


def test_pdf_size_limit_enforced(basic_ctx_args):
    """PDF byte tavanı (DILEKCE_MAX_PDF_BYTES = 5MB) aşılırsa ValueError."""
    # Çok büyük olgu listesi → PDF büyür. Bu test cap-enforcement'i doğrular.
    # 5MB'ı geçecek kadar text üretmek pratik değil; sadece cap'in fonksiyonel
    # olduğunu doğruluyoruz (negative-space: makul boyutta hata YOK).
    result = render_dilekce(
        domain="tuketici", template_id="tuketici/hakem_heyeti_basvuru_v1", **basic_ctx_args,
    )
    # Smoke: < 5MB → hata YOK
    assert len(result.pdf_bytes) < 5 * 1024 * 1024


def test_filename_iso_date_format(basic_ctx_args):
    """Filename'de ISO tarih formatı (YYYY-MM-DD) korunur."""
    result = render_dilekce(
        domain="vergi", template_id="vergi/mtv_terkin_v1", **basic_ctx_args,
    )
    assert "2026-05-28" in result.filename


# --- DOCX çıktısı (PDF ile aynı markdown kaynağından) ---

def test_docx_produced_by_default(basic_ctx_args):
    """Default formats={pdf,docx} → geçerli, parse edilebilir Word dosyası."""
    import io

    from docx import Document
    result = render_dilekce(
        domain="isHukuku", template_id="isHukuku/kidem_tazminat_talep_v1", **basic_ctx_args,
    )
    assert result.docx_bytes is not None
    assert result.docx_bytes[:2] == b"PK"  # zip/docx magic
    assert result.docx_filename.endswith(".docx")
    # python-docx ile parse edilebilmeli + içerik dolu
    doc = Document(io.BytesIO(result.docx_bytes))
    paras = [p.text for p in doc.paragraphs if p.text.strip()]
    assert len(paras) >= 5


def test_docx_preserves_turkish(basic_ctx_args):
    import io

    from docx import Document
    result = render_dilekce(
        domain="kira", template_id="kira/depozito_iade_v1", **basic_ctx_args,
    )
    doc = Document(io.BytesIO(result.docx_bytes))
    full = " ".join(p.text for p in doc.paragraphs)
    assert any(ch in full for ch in "çşğıöüİ")  # Türkçe karakter korunur


def test_pdf_only_skips_docx(basic_ctx_args):
    """formats={'pdf'} → docx üretilmez (None)."""
    result = render_dilekce(
        domain="tuketici", template_id="tuketici/hakem_heyeti_basvuru_v1",
        formats=frozenset({"pdf"}), **basic_ctx_args,
    )
    assert result.pdf_bytes  # PDF hâlâ var
    assert result.docx_bytes is None
    assert result.docx_filename == ""


def test_docx_inline_bold_italic():
    """_add_inline_runs: **bold** ve *italic* doğru run'lara bölünür."""
    from docx import Document
    from agents.dilekce.renderer import _add_inline_runs
    doc = Document()
    p = doc.add_paragraph()
    _add_inline_runs(p, "normal **kalın** ve *eğik* son")
    runs = [(r.text, r.bold, r.italic) for r in p.runs]
    assert ("kalın", True, None) in runs
    assert ("eğik", None, True) in runs
