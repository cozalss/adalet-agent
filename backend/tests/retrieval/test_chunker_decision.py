"""chunk_decision — section-aware chunking (Sprint-5 W14.7)."""

from __future__ import annotations

from retrieval.chunker import chunk_decision, chunk_text


def test_chunk_decision_returns_sections_when_markers_present():
    """Bedesten karar metni gerekçe + hüküm marker'ı içerirse, chunk metadata'sında section eklenir."""
    text = """
DAVA: Davacı vekili dava dilekçesinde özetle; müvekkilinin işyerinde 5 yıl çalıştığını,
işveren tarafından haksız fesih yapıldığını, kıdem tazminatı talep ettiğini belirtmiştir.

GEREKÇE: Mahkememizce yapılan değerlendirmede, davacının iş sözleşmesinin haklı sebep
gösterilmeden feshedildiği anlaşılmıştır. 4857 sayılı İş Kanunu'nun 17. maddesi gereğince
işverenin süreli fesih bildirimini usulüne uygun yapmadığı, davacının yıllık izinlerini
tam olarak kullanmadığı belirlenmiştir. Bu nedenle davacı lehine karar verilmesi gerekir.

HÜKÜM: Açıklanan nedenlerle davanın KISMEN KABULÜNE; 25.000 TL kıdem tazminatının
davalıdan alınarak davacıya verilmesine, fazlaya ilişkin talebin reddine karar verildi.
"""
    chunks = chunk_decision(text.strip())
    assert len(chunks) >= 3
    sections = {ch.metadata.get("section") for ch in chunks}
    # Üç ana section da yakalanmalı
    assert "olay" in sections
    assert "gerekce" in sections
    assert "sonuc" in sections


def test_chunk_decision_fallback_when_no_markers():
    """Section marker yoksa flat chunk list, hepsi 'gerekce' default."""
    text = "Bu bir test kararıdır. " * 100  # >chunk_chars
    chunks = chunk_decision(text)
    assert len(chunks) >= 1
    assert all(ch.metadata.get("section") == "gerekce" for ch in chunks)


def test_chunk_decision_classifies_karar_as_sonuc():
    """KARAR: başlığı sonuç olarak sınıflandırılmalı (HÜKÜM eşdeğeri)."""
    text = """
OLAY: Olay özeti.

KARAR: Davanın kabulüne karar verildi.
""".strip()
    chunks = chunk_decision(text, min_chars=10)
    sections = [ch.metadata.get("section") for ch in chunks]
    assert "sonuc" in sections


def test_chunk_decision_empty_text_returns_empty():
    """Boş metin → boş liste."""
    assert chunk_decision("") == []
    assert chunk_decision("   ") == []


def test_chunk_decision_short_text_below_min_chars():
    """min_chars altı metin chunk_text fallback'inde de boş döner."""
    short = "Kısa."
    assert chunk_decision(short, min_chars=80) == []


def test_chunk_decision_preserves_text_content():
    """Section'lara bölme sonrası önemli ifade'ler korunmalı."""
    text = """
GEREKÇE: TBK m.344 uyarınca kira artışı TÜFE'yi aşamaz.
HÜKÜM: Davanın kabulüne.
""".strip()
    chunks = chunk_decision(text, min_chars=10)
    full = " ".join(ch.text for ch in chunks)
    assert "TBK m.344" in full
    assert "kabulüne" in full


def test_chunk_decision_default_chunk_text_compatible():
    """chunk_decision marker yoksa chunk_text'in verdiği bölünme ile uyumlu."""
    text = "Bir metin. " * 200
    flat = chunk_text(text)
    decision_chunks = chunk_decision(text)
    # Aynı sayıda chunk üretmeli (sadece section metadata farklı)
    assert len(flat) == len(decision_chunks)
