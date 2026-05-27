"""retrieval/turkish_text.py — snowballstemmer + morfoloji + keyword recall.

Sprint-4 W1.5: Türkçe stemming entegrasyonu testleri.
"""

from __future__ import annotations

from retrieval import turkish_text as tt


def test_stem_word_basic_inflections():
    """Türkçe ek varyasyonları aynı köke iner."""
    assert tt.stem_word("kıdem") == tt.stem_word("kıdemin")
    assert tt.stem_word("tazminat") == tt.stem_word("tazminatlar")
    assert tt.stem_word("tazminat") == tt.stem_word("tazminatı")


def test_stem_word_empty_safe():
    assert tt.stem_word("") == ""


def test_tokenize_removes_stopwords():
    out = tt.tokenize("Kıdem tazminatı ve ihbar tazminatı nedir?")
    # "ve", "nedir" stopword (nedir → değil — bizim listemizde değil ama de/da var)
    assert "ve" not in out
    assert "kıdem" in out
    assert "tazminatı" in out


def test_tokenize_handles_punctuation():
    out = tt.tokenize("Madde 11; tüketici, satıcıya ihtar gönderir!")
    # noktalama temizlenir
    assert ";" not in out
    assert "11" in out
    assert "madde" in out


def test_stem_text_full_question():
    stems = tt.stem_text("Kira sözleşmesinin feshi nasıl yapılır?")
    # "nasıl" stopword listede; kira ve sözleşme + fesh stem'leri kalır
    assert any(s.startswith("kira") for s in stems)
    assert any("sözleş" in s or "sözleşm" in s for s in stems)
    assert any("fesh" in s or "feshi" in s or "fes" in s for s in stems)


def test_keyword_overlap_stem_aware_matches_inflections():
    """Cevap çekimli formda olsa bile stem-aware match yakalar."""
    answer = "İşçinin kıdemine bakılarak tazminatları hesaplanır."
    expected = ["kıdem tazminatı", "hesaplama"]
    recall = tt.keyword_overlap(answer, expected, use_stem=True)
    # En azından "kıdem tazminatı" hit etmeli (her iki stem cevapta)
    assert recall >= 0.5


def test_keyword_overlap_plain_lower_substring():
    """use_stem=False — eski davranış (substring match)."""
    answer = "İşçinin kıdem tazminatı hesaplanır."
    expected = ["kıdem tazminatı"]
    recall = tt.keyword_overlap(answer, expected, use_stem=False)
    assert recall == 1.0


def test_keyword_overlap_empty_inputs():
    assert tt.keyword_overlap("", ["kıdem"], use_stem=True) == 0.0
    assert tt.keyword_overlap("cevap", [], use_stem=True) == 0.0


def test_morphological_variants_produces_alternatives():
    """LLM-siz fallback — stem + ek varyasyonları üretir."""
    variants = tt.morphological_variants(
        "Kıdem tazminatı nasıl hesaplanır?",
        max_variants=3,
    )
    # En az 1 varyant üretmeli (stem form)
    assert len(variants) >= 1
    # Hepsi orijinalden farklı
    assert all(v.lower() != "kıdem tazminatı nasıl hesaplanır?" for v in variants)


def test_morphological_variants_empty_input():
    assert tt.morphological_variants("", max_variants=3) == []
    assert tt.morphological_variants("   ", max_variants=3) == []


def test_morphological_variants_caps_at_max():
    variants = tt.morphological_variants("Kira sözleşmesi feshi", max_variants=2)
    assert len(variants) <= 2


# --- Türkçe İ/I casefolding (W14) ---


def test_tr_lower_handles_turkish_dotted_i():
    """Python str.lower() İ→i̇ (combining dot) üretir; tr_lower düzeltir."""
    assert tt.tr_lower("İŞÇİ") == "işçi"
    assert tt.tr_lower("İş Kanunu") == "iş kanunu"
    # Türkçe I → ı (dotsuz)
    assert tt.tr_lower("IK") == "ık"
    assert tt.tr_lower("İK") == "ik"
    # combining dot above (U+0307) ASLA üretilmemeli
    assert "̇" not in tt.tr_lower("İDARİ HUKUK")


def test_stem_word_case_insensitive_turkish_i():
    """'İş' ve 'iş' aynı stem'e inmeli — eskiden combining dot ayırıyordu."""
    assert tt.stem_word("İş") == tt.stem_word("iş")
    assert tt.stem_word("İCRA") == tt.stem_word("icra")


def test_tokenize_uppercase_turkish_matches_lowercase():
    """Büyük harfli Türkçe başlık küçük harfle aynı token üretmeli."""
    assert tt.tokenize("İŞÇİ HAKLARI") == tt.tokenize("işçi hakları")
    # combining dot içeren token oluşmamalı
    assert all("̇" not in t for t in tt.tokenize("İHTARNAME"))


def test_keyword_overlap_matches_across_turkish_case():
    """Büyük-İ ile yazılmış cevapta küçük-i beklenen kelime yakalanmalı."""
    answer = "İŞÇİNİN KIDEM TAZMİNATI ÖDENİR."
    recall = tt.keyword_overlap(answer, ["kıdem tazminatı"], use_stem=False)
    assert recall == 1.0


# --- 4-yönlü ünlü uyumu -lık/-lik/-luk/-lük (W14) ---


def test_lik_suffix_vowel_harmony():
    assert tt._lik_suffix("kira") == "lık"      # son ünlü a → ı
    assert tt._lik_suffix("vergi") == "lik"     # son ünlü i → i
    assert tt._lik_suffix("hukuk") == "luk"     # son ünlü u → u
    assert tt._lik_suffix("söz") == "lük"       # son ünlü ö → ü


def test_morphological_variants_uses_vowel_harmonic_suffix():
    """Variant-3 nominal eki ünlü uyumlu olmalı (eski bug hep 'lik' üretiyordu).

    Ek STEM'lenmiş ilk köke ekleniyor → beklenen formu stemmer'dan bağımsız
    hesaplayıp doğruluyoruz (kırılgan literal yerine).
    """
    q = "kira artışı oranı"
    stems = tt.stem_text(q)
    variants = tt.morphological_variants(q, max_variants=3)
    expected_suffix = tt._lik_suffix(stems[0])
    expected_nominal = stems[0] + expected_suffix
    assert any(expected_nominal in v for v in variants)
    # Harmony 'lik' DEĞİLSE, yanlış 'lik' formu üretilmemeli (regresyon guard)
    if expected_suffix != "lik":
        assert not any(stems[0] + "lik" in v for v in variants)
