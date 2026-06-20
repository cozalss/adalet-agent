"""Dilekçe teklifine kısa onay ("isterim") → kapsam-dışı reddi YERİNE teklifi uygula.

Bug: asistan "...ihtarname hazırlamamı ister misiniz?" diye KENDİSİ teklif edince,
kullanıcının "isterim" yanıtı bağlam kaybedip "uzmanlık alanım dışında" reddine düşüyordu
(asistan kendi teklifini reddediyordu). Fix: ask._resolve_affirmed_offer.
"""

from __future__ import annotations

from api.routes.ask import (
    _is_affirmation,
    _last_assistant_offered_dilekce,
    _last_user_question,
    _resolve_affirmed_offer,
)

_OFFER = (
    "Ev sahibinize ... bildirin.\n\n"
    "💡 *Kira artışına itiraz için ihtarname taslağı hazırlamamı ister misiniz?*"
)
_HISTORY = [
    {"role": "user", "content": "ev sahibim kira artışı istiyor ne kadar olabilir", "domain": "kira"},
    {"role": "assistant", "content": _OFFER},
]


# --- _is_affirmation ---

def test_short_affirmations_detected():
    for q in ("isterim", "Evet", "olur", "lütfen", "tamam", "isterim lütfen", "evet hazırla"):
        assert _is_affirmation(q), q


def test_real_followups_not_affirmation():
    # Uzun/içerikli takip soruları onay sayılmaz (yanlışlıkla teklif tetiklenmesin).
    for q in ("evet ama 1 yıldan azsa ne olur", "kira artışı ne kadar olabilir",
              "peki tahliye davası nasıl açılır"):
        assert not _is_affirmation(q), q


# --- offer + prior-question tespiti ---

def test_detects_dilekce_offer_in_last_assistant_turn():
    assert _last_assistant_offered_dilekce(_HISTORY) is True
    # teklif içermeyen normal cevap → False
    assert _last_assistant_offered_dilekce(
        [{"role": "assistant", "content": "Kira artışı TÜFE ile sınırlıdır."}]
    ) is False


def test_last_user_question_returns_prior():
    assert _last_user_question(_HISTORY) == "ev sahibim kira artışı istiyor ne kadar olabilir"


# --- _resolve_affirmed_offer (entegrasyon) ---

def test_affirm_after_offer_resolves_prior_question():
    prior = _resolve_affirmed_offer("isterim", _HISTORY)
    assert prior == "ev sahibim kira artışı istiyor ne kadar olabilir"


def test_no_resolve_when_no_offer():
    # Önceki asistan turu teklif içermiyorsa onay da olsa None (yanlış tetikleme yok).
    hist = [{"role": "user", "content": "kira sorum"}, {"role": "assistant", "content": "Kira ... cevabı."}]
    assert _resolve_affirmed_offer("isterim", hist) is None


def test_no_resolve_for_non_affirmation():
    assert _resolve_affirmed_offer("peki tahliye nasıl olur", _HISTORY) is None


def test_no_resolve_empty_history():
    assert _resolve_affirmed_offer("isterim", []) is None
