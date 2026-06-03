"""retrieval/chunker.chunk_mevzuat — uzun-madde alt-bölme (denetim 2026-06-04, #2).

Çok-fıkralı uzun maddeler tek dev chunk olarak embed edilince dense vektör tüm madde
üzerinde ortalanır → spesifik fıkra sinyali dilüe olur. Uzun madde paragraf-aware alt-chunk'lara
bölünür; her alt-chunk AYNI madde_no'yu taşır (citation/fetch_maddeler bozulmaz).
"""

from __future__ import annotations

from retrieval.chunker import _MEVZUAT_SUBCHUNK_THRESHOLD, chunk_mevzuat


def test_short_article_single_chunk_unchanged():
    """Kısa madde tek chunk kalır (davranış değişmez) + madde_no korunur."""
    chunks = chunk_mevzuat("Madde 11 — Tüketici cayma hakkını 14 gün içinde kullanabilir.")
    assert len(chunks) == 1
    assert chunks[0].metadata["madde_no"] == 11


def test_multiple_short_articles_one_chunk_each():
    text = "Madde 1 — Birinci hüküm.\nMadde 2 — İkinci hüküm.\nMadde 3 — Üçüncü hüküm."
    chunks = chunk_mevzuat(text)
    assert len(chunks) == 3
    assert [c.metadata["madde_no"] for c in chunks] == [1, 2, 3]


def test_long_article_subsplit_keeps_same_madde_no():
    """Uzun (>eşik) çok-fıkralı madde → ≥2 alt-chunk, HEPSİ aynı madde_no, ilki başlığı korur."""
    fikra = "Bu fıkra hükmü ayrıntılı biçimde düzenlenmiş olup uzun bir metin içerir ve devam eder."
    body = "\n\n".join(f"({i}) {fikra} {fikra} {fikra}" for i in range(1, 12))
    text = f"Madde 359 — {body}"
    assert len(text) > _MEVZUAT_SUBCHUNK_THRESHOLD

    chunks = chunk_mevzuat(text)
    assert len(chunks) >= 2, "uzun madde alt-bölünmeli"
    assert all(c.metadata["madde_no"] == 359 for c in chunks), "tüm alt-chunk aynı madde_no"
    assert "Madde 359" in chunks[0].text, "ilk alt-chunk madde başlığını korumalı"


def test_article_without_number_has_empty_metadata():
    chunks = chunk_mevzuat("Geçici bir hüküm; madde numarası içermez.")
    assert len(chunks) == 1
    assert "madde_no" not in chunks[0].metadata
