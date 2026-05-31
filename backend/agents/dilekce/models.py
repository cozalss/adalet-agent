"""Dilekçe render girdi/çıktı modelleri — immutable dataclass'lar.

SIFIR HALÜSİNASYON (CLAUDE.md §1): DilekceContext yalnız VERIFIED claim'lerden
ve KAYNAKLI mevzuat referanslarından kurulur. Render aşamasında LLM çağrılmaz
— jinja2 string interpolation deterministiktir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agents.state import Citation, Domain


@dataclass(frozen=True)
class DilekceContext:
    """Render için minimum yeterli, doğrulanmış girdi paketi.

    Args:
        domain: Hukuk alanı (template seçimi için).
        template_id: "tuketici/ayipli_mal_iade_v1" gibi qualified id.
        soru: Vatandaşın orijinal sorusu (özet için).
        olgular: case_facts'tan + verified claim'lerden derlenen somut olgu
            listesi. Örn ["Süre: 3 ay", "Tutar: 5000 TL"]. Liste boş olabilir.
        hukuki_dayanak: Yalnız mevzuat_refs Citation'ları (gerçek madde no
            + kanun adı). Boş ise template "[DAYANAK BULUNAMADI]" yazar.
        emsal_destek: emsal_refs Citation'ları (opsiyonel, top 3-5).
        ozet_metin: VERIFIED draft cümleleri (kullanıcının durumu özeti).
        tarih: ISO-format "YYYY-MM-DD" — render saatinde set edilir.
        user_meta: state.user_meta'dan (sehir, taraf vs.). Eksik alanlar
            jinja'da {{ placeholder }} olarak kalır (KVKK: gerçek TC YAZILMAZ).
    """

    domain: Domain
    template_id: str
    soru: str
    olgular: list[str]
    hukuki_dayanak: list[Citation]
    emsal_destek: list[Citation]
    ozet_metin: str
    tarih: str
    user_meta: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DilekceResult:
    """Render çıktısı — markdown source + PDF/DOCX bytes + audit metadata.

    DOCX, vatandaş/avukat düzenleyebilsin diye PDF'e ek olarak üretilir
    (aynı markdown kaynağından python-docx ile). docx_bytes None ise
    DOCX istenmedi (formats={"pdf"}).
    """

    template_id: str
    markdown: str                       # state['dilekce_md']'e yazılır (transparency)
    pdf_bytes: bytes                    # state['dilekce_pdf_bytes']'a yazılır
    filename: str                       # PDF Content-Disposition için
    n_dayanak: int                      # audit metric
    n_emsal: int                        # audit metric
    docx_bytes: bytes | None = None     # state['dilekce_docx_bytes']'a yazılır
    docx_filename: str = ""             # DOCX Content-Disposition için


__all__ = ("DilekceContext", "DilekceResult")
