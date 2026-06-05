"""Adaptif cevap uzunluğu — token tavanı soru-karmaşıklığına göre seçilir (2026-06-05).

Basit/tanımsal → kısa tavan; karmaşık/olgu-zengin → uzun tavan. Sabit kelime-aralığı kaldırıldı;
gerçek uzunluğu prompt sürer, bu yalnız tavan (kesilme/şişme önler).
"""

from __future__ import annotations

from agents.config import DRAFT_MAX_TOKENS, DRAFT_MIN_TOKENS
from agents.nodes.draft import _adaptive_max_tokens, _prune_sections_for_definitional

_MID = (DRAFT_MIN_TOKENS + DRAFT_MAX_TOKENS) // 2

_FIVE_SECTION = (
    "**Kısa cevap:** Kıdem tazminatı işçinin hakkıdır. [src: m-EIK-14]\n\n"
    "**Durumunuza uygulama:** Sizin durumunuzda değerlendirme.\n\n"
    "**Dayanak:** 1475 sayılı İş Kanunu m.14. [src: m-EIK-14]\n\n"
    "**Ne yapmalı:** 1. Başvurun. 2. Bekleyin.\n\n"
    "**Dikkat:** Zamanaşımı var."
)


def test_simple_definitional_short_cap():
    # Kısa + olgusuz tanım sorusu → en kısa tavan.
    assert _adaptive_max_tokens("kıdem tazminatı nedir", {}) == DRAFT_MIN_TOKENS


def test_fact_rich_complex_long_cap():
    # ≥2 olgu → karmaşık → en uzun tavan (kesilmesin).
    facts = {"sure": "2 yıl", "olay": "haksız fesih", "tutar": "30000"}
    assert _adaptive_max_tokens("işten çıkarıldım", facts) == DRAFT_MAX_TOKENS


def test_long_question_complex_cap():
    # Uzun/çok-konulu soru (olgu az olsa da) → uzun tavan.
    long_q = "merhaba " * 40  # >180 karakter
    assert _adaptive_max_tokens(long_q, {}) == DRAFT_MAX_TOKENS


def test_standard_midpoint_cap():
    # Tek olgu + orta uzunluk → standart (orta tavan).
    facts = {"olay": "ev sahibi depozitoyu vermiyor"}
    q = "ev sahibim depozitomu geri vermiyor ne yapabilirim acaba"  # 90-180 arası, 1 olgu
    assert _adaptive_max_tokens(q, facts) == _MID


def test_adaptive_range_ordered():
    # Taban < orta < tavan (mantık tutarlılığı).
    assert DRAFT_MIN_TOKENS < _MID < DRAFT_MAX_TOKENS


# --- bölüm-adaptasyonu (tanımsal prune) ---

def test_definitional_prunes_to_short():
    out = _prune_sections_for_definitional(_FIVE_SECTION, "kıdem tazminatı nedir", {})
    assert "**Kısa cevap:**" in out and "**Dayanak:**" in out
    assert "**Durumunuza uygulama:**" not in out  # uygulanamaz → kesildi
    assert "**Ne yapmalı:**" not in out
    assert "**Dikkat:**" not in out
    assert "[src: m-EIK-14]" in out  # grounding korunur (Dayanak'taki cite kalır)


def test_fact_rich_untouched():
    # ≥2 gerçek olgu → durumsal → tüm bölümler anlamlı, dokunma.
    out = _prune_sections_for_definitional(
        _FIVE_SECTION, "kıdem tazminatı nedir", {"olay": "haksız fesih", "sure": "5 yıl"})
    assert out == _FIVE_SECTION


def test_definitional_with_one_spurious_fact_still_prunes():
    # Triaj tanımsal soruya 1 spurious olgu atsa bile (stokastik) → yine prune (kapı soru-işareti birincil).
    out = _prune_sections_for_definitional(_FIVE_SECTION, "kıdem tazminatı nedir", {"olay": "kıdem"})
    assert "**Ne yapmalı:**" not in out and "**Durumunuza uygulama:**" not in out


def test_situational_marker_untouched():
    # Kullanıcı olayını anlatıyor ("vermiyor") → durumsal → dokunma (tanım-işareti olmasa da).
    out = _prune_sections_for_definitional(_FIVE_SECTION, "ev sahibim depozitomu vermiyor", {})
    assert out == _FIVE_SECTION


def test_already_short_untouched():
    short = "**Kısa cevap:** Evet. [src: m-EIK-14]\n\n**Dayanak:** m.14. [src: m-EIK-14]"
    assert _prune_sections_for_definitional(short, "kıdem nedir", {}) == short
