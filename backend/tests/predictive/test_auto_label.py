"""auto_label.build_label_record — leak-free silver etiketleme (saf-mantık).

HF parquet/network gerektirmez; sentetik karar metinleriyle çekirdeği doğrular.
En kritik invariant: model girdisi (input_text) HÜKÜM bölümünü İÇERMEZ (leak yok).
"""

from __future__ import annotations

from retrieval.turkish_text import tr_lower
from scripts.predictive.auto_label import build_label_record


def test_tr_lower_is_length_preserving():
    """_split_hukum, text_low offset'ini ham text'te kullanır — tr_lower
    karakter SAYISINI korumalı (İ→i̇ genişlemesi olsaydı offset kayardı).
    Bu invariant leak-free split'in doğruluğunu garanti eder."""
    for s in ["HÜKÜM:", "İSTİNAF", "IŞIK", "ÇĞÖŞÜİ", "Davanın KABULÜNE", "ABCİ123"]:
        assert len(tr_lower(s)) == len(s), f"tr_lower uzunluğu bozdu: {s!r}"

# 9. Hukuk Dairesi → isHukuku (in-scope). Olay/gerekçe verdict-keyword içermez.
_KARAR_KAZANDI = (
    "**9. Hukuk Dairesi 2019/1234 E. , 2020/5678 K.**\n\n"
    "DAVA: Davacı işçi, iş sözleşmesinin haksız feshedildiğini ileri sürerek "
    "kıdem tazminatı talep etmiştir. Davacının işyerinde sekiz yıl çalıştığı, "
    "ücretinin zamanında ödenmediği dosya kapsamından anlaşılmaktadır. "
    "Tanık beyanları davacıyı doğrulamaktadır.\n\n"
    "HÜKÜM: Davanın kabulüne, kıdem tazminatının davalıdan tahsiline "
    "karar verilmiştir."
)


def test_label_extracted_from_hukum():
    rec = build_label_record(_KARAR_KAZANDI, "h-1")
    assert rec is not None
    assert rec.domain == "isHukuku"
    assert rec.label == "kazandi"
    assert "9. Hukuk Dairesi" in rec.chamber


def test_input_text_excludes_hukum_no_leak():
    """KRİTİK: model girdisi hüküm verdict-kelimelerini İÇERMEMELİ (label leak)."""
    rec = build_label_record(_KARAR_KAZANDI, "h-1")
    assert rec is not None
    low = rec.input_text.lower()
    # Hükümdeki sonuç-kelimeleri girdiye sızmamalı:
    assert "kabulüne" not in low
    assert "tahsiline" not in low
    # Ama olay/gerekçe girdide olmalı:
    assert "kıdem tazminatı" in low
    # Hüküm excerpt label kaynağını taşımalı (denetim için):
    assert "kabul" in rec.hukum_excerpt.lower()


def test_scope_out_chamber_returns_none():
    """2. Hukuk Dairesi (aile) CHAMBER_TO_DOMAIN'de yok → kapsam dışı → None."""
    text = (
        "**2. Hukuk Dairesi 2019/1 E. , 2020/2 K.**\n\n"
        "DAVA: boşanma. " + "x" * 300 + "\n\nHÜKÜM: Davanın kabulüne."
    )
    assert build_label_record(text, "h-2") is None


def test_no_signal_hukum_returns_none():
    """Hükümde net sonuç sinyali yoksa silver-label üretme (gürültü ekleme)."""
    text = (
        "**9. Hukuk Dairesi 2019/3 E. , 2020/4 K.**\n\n"
        "DAVA: " + "uzun olay anlatımı " * 30 + "\n\n"
        "HÜKÜM: Dosyanın ilgili daireye gönderilmesine."  # kabul/ret sinyali yok
    )
    assert build_label_record(text, "h-3") is None


def test_short_input_returns_none():
    """Hüküm çıkınca girdi çok kısaysa (anlamlı olay yok) → None."""
    text = "**9. Hukuk Dairesi 2019/5 E.**\nHÜKÜM: Davanın reddine karar verildi."
    assert build_label_record(text, "h-4") is None


def test_reddine_labels_kaybetti():
    text = (
        "**3. Hukuk Dairesi 2019/9 E. , 2020/9 K.**\n\n"
        "DAVA: Kiracı, depozitonun iadesini talep etmiştir. Dosyadaki belgelere "
        "göre kiralananın tahliyesinde hasar tespit edilmiştir ve bilirkişi "
        "raporu bu durumu teyit etmektedir.\n\n"
        "HÜKÜM: Davanın reddine karar verilmiştir."
    )
    rec = build_label_record(text, "h-5")
    assert rec is not None
    assert rec.label == "kaybetti"
    assert rec.domain == "kira"
    assert "reddine" not in rec.input_text.lower()
