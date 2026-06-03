"""api/pii.py — gerçek-dünya PII format varyantları (denetim 2026-06-04 bulgusu).

mask_pii eskiden boşluklu/noktalı TCKN, parantezli/sabit-hat telefon ve küçük-harf IBAN'ı
KAÇIRIYORDU → bu PII değerleri log/belge/session'da HAM kalıyordu. Bu testler varyant
kapsamasını kilitler. Sahte (geçersiz) PII kullanılır — CLAUDE.md temiz-repo kuralı.
"""

from __future__ import annotations

import pytest

from api.pii import mask_pii


@pytest.mark.parametrize("text", [
    "TC kimlik: 123 456 789 01 numaralı kişi",      # boşluklu
    "TCKN 123.456.789.01 olarak kayıtlı",            # noktalı
    "Kimliğim 12345678901 şeklinde",                 # bitişik (regresyon)
])
def test_tckn_separated_variants_masked(text):
    r = mask_pii(text)
    assert r.counts.get("tckn", 0) >= 1, f"TCKN kaçtı: {text!r}"
    assert "[PII_MASKED]" in r.masked_text


@pytest.mark.parametrize("text", [
    "Beni (0555) 123 45 67 numarasından arayın",     # parantezli mobil
    "Sabit hattım 0312 4567890",                      # sabit hat (alan kodu 3xx)
    "+90 532 123 45 67 üzerinden ulaşın",            # +90 ülke kodu
    "0555 123 45 67 ara",                             # düz mobil (regresyon)
])
def test_phone_format_variants_masked(text):
    r = mask_pii(text)
    assert r.counts.get("phone", 0) >= 1, f"telefon kaçtı: {text!r}"


def test_iban_lowercase_masked():
    """Küçük-harf 'tr…' IBAN da maskelenmeli (IGNORECASE)."""
    r = mask_pii("Hesabım tr120001001712345678901234 numaralı")
    assert r.counts.get("iban", 0) >= 1
    assert "tr12" not in r.masked_text.lower()


def test_iban_uppercase_still_masked_and_not_split_as_tckn():
    """Regresyon: IBAN TCKN'den önce maskelenir → IBAN olarak sayılır, tckn'e bölünmez."""
    r = mask_pii("IBAN: TR12 0001 0017 1234 5678 9012 34 hesabıma yatırın")
    assert r.counts.get("iban") == 1
    assert "tckn" not in r.counts  # IBAN haneleri TCKN olarak yanlış sayılmamalı


def test_plate_not_caught_as_phone():
    """Regresyon: plaka ('34 ABC 123') genişletilmiş telefon desenine düşmemeli."""
    r = mask_pii("Aracım 34 ABC 123 plakalı")
    assert r.counts.get("plate", 0) >= 1
    assert r.counts.get("phone", 0) == 0
