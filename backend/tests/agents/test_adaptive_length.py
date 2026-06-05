"""Adaptif cevap uzunluğu — token tavanı soru-karmaşıklığına göre seçilir (2026-06-05).

Basit/tanımsal → kısa tavan; karmaşık/olgu-zengin → uzun tavan. Sabit kelime-aralığı kaldırıldı;
gerçek uzunluğu prompt sürer, bu yalnız tavan (kesilme/şişme önler).
"""

from __future__ import annotations

from agents.config import DRAFT_MAX_TOKENS, DRAFT_MIN_TOKENS
from agents.nodes.draft import _adaptive_max_tokens

_MID = (DRAFT_MIN_TOKENS + DRAFT_MAX_TOKENS) // 2


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
