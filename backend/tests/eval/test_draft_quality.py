"""draft_quality harness — saf metrik fonksiyonları (LLM/Qdrant YOK)."""

from __future__ import annotations

from eval.draft_quality import (
    has_short_answer,
    is_truncated,
    length_in_target,
    measure,
    src_tag_coverage,
    strip_boilerplate_block,
    turkish_purity,
    word_count,
)

# --------------------------------------------------------------------------
#  has_short_answer
# --------------------------------------------------------------------------


def test_short_answer_detected_with_markdown():
    assert has_short_answer("**Kısa cevap:** Depozitonuzu isteyebilirsiniz.") is True


def test_short_answer_detected_plain():
    assert has_short_answer("Kısa cevap: Evet, hakkınız var.") is True


def test_short_answer_absent():
    assert has_short_answer("Merhaba, durumunuz şöyle...") is False


# --------------------------------------------------------------------------
#  turkish_purity
# --------------------------------------------------------------------------


def test_purity_full_turkish():
    assert turkish_purity("Tamamen Türkçe bir cümle: çğşıöü ÇĞŞİÖÜ.") == 1.0


def test_purity_detects_cjk_leakage():
    assert turkish_purity("Türkçe 中文 karışık metin") < 1.0


def test_purity_empty_is_safe():
    # Boş/harfsiz metin patlamaz (ZeroDivision yok)
    assert turkish_purity("12345 .,!?") == 1.0


# --------------------------------------------------------------------------
#  src_tag_coverage
# --------------------------------------------------------------------------


def test_src_coverage_all_tagged():
    text = (
        "Tüketici ayıplı malı iade edebilir [src: m-TKHK-11]. "
        "Satıcı ayıbı ispatla yükümlüdür [src: m-TKHK-10]."
    )
    assert src_tag_coverage(text) == 1.0


def test_src_coverage_none_tagged():
    text = "Bu bir iddiadır kaynaksız. Bu da başka bir kaynaksız iddiadır burada."
    assert src_tag_coverage(text) == 0.0


# --------------------------------------------------------------------------
#  word_count / length_in_target
# --------------------------------------------------------------------------


def test_word_count_strips_src_tags():
    # [src: ...] etiketi kelime sayımına girmemeli
    assert word_count("iki kelime [src: abc]") == 2


def test_length_in_target_band():
    assert length_in_target(160) is True
    assert length_in_target(220) is True
    assert length_in_target(159) is False
    assert length_in_target(221) is False


# --------------------------------------------------------------------------
#  strip_boilerplate_block + measure (orkestratör)
# --------------------------------------------------------------------------


def test_strip_boilerplate_removes_kaynaklar_tail():
    body = "**Kısa cevap:** Hakkınız var [src: x]."
    full = f"{body}\n\n---\n**Kaynaklar:**\n- [Mevzuat] ...\n\n⚠️ Bu cevap..."
    stripped = strip_boilerplate_block(full)
    assert "Kaynaklar" not in stripped
    assert "Kısa cevap" in stripped


def test_measure_returns_all_dimensions():
    out = measure("**Kısa cevap:** Tüketici iade hakkına sahiptir [src: m-TKHK-11].")
    assert set(out) >= {"has_short_answer", "turkish_purity", "src_coverage", "word_count",
                        "is_truncated"}
    assert out["has_short_answer"] is True
    assert 0.0 <= out["turkish_purity"] <= 1.0


# --------------------------------------------------------------------------
#  is_truncated — cevap kesilme tespiti
# --------------------------------------------------------------------------


def test_truncated_when_ends_mid_sentence():
    # Token cap'e takılmış: cümle ortasında, noktalama yok
    assert is_truncated("**Kısa cevap:** Tüketici olarak iade talebinizi satıcıya") is True


def test_not_truncated_with_terminal_punctuation():
    assert is_truncated("**Kısa cevap:** Tüketici iade hakkına sahiptir.") is False


def test_not_truncated_ending_with_src_tag():
    assert is_truncated("**Kısa cevap:** Hakkınız var [src: m-TKHK-11]") is False


def test_not_truncated_when_boilerplate_tail_present():
    # Gövde düzgün bitiyor, sonra finalize boilerplate eklenmiş → truncation değil
    full = "**Kısa cevap:** İade hakkınız var.\n\n---\n**Kaynaklar:**\n- ...\n\n⚠️ Bu cevap..."
    assert is_truncated(full) is False


def test_empty_body_not_truncated():
    # Boş gövde ayrı bir hata; truncation sayılmaz
    assert is_truncated("") is False
