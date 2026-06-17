from __future__ import annotations

from retrieval.typo_tolerance import (
    ascii_fold,
    build_query_variants,
    normalize_for_match,
    typo_retrieval_variants,
)


def test_normalize_for_match_strips_zero_width_and_preserves_turkish_lower():
    assert normalize_for_match("  İŞÇİ\u200b  ") == "işçi"
    assert ascii_fold("TÜFE kira artışı") == "tufe kira artisi"


def test_build_query_variants_corrects_legal_typos():
    built = build_query_variants("kidem tazmnatı nasıl hesaplanır")
    assert built.corrected is not None
    assert "kıdem tazminatı" in built.corrected
    assert {c.original for c in built.corrections} >= {"kidem", "tazmnatı"}


def test_exact_diacritic_fold_correction_for_short_legal_terms():
    built = build_query_variants("kira tufe ustunde arttı")
    assert built.corrected is not None
    assert "tüfe" in built.corrected


def test_protects_numbers_law_codes_and_article_refs():
    built = build_query_variants("TBK m. 344 kira artis siniri")
    assert built.corrected is not None
    assert "344" in built.corrected
    assert "tbk" in built.corrected
    assert "artış" in built.corrected


def test_split_word_boundary_typo_variant():
    built = build_query_variants("iseiade davası açabilir miyim")
    assert built.corrected is not None
    assert "işe iade" in built.corrected


def test_typo_retrieval_variants_respects_feature_flag(monkeypatch):
    monkeypatch.setenv("TYPO_TOLERANCE_ENABLED", "0")
    assert typo_retrieval_variants("kidem tazmnatı") == []

    monkeypatch.setenv("TYPO_TOLERANCE_ENABLED", "1")
    assert typo_retrieval_variants("kidem tazmnatı")
