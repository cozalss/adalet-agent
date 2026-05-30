"""Policy engine — cevap-yolu kararı (saf fonksiyon, LLM yok).

decide_path bir state dict'inden deterministik bir karar üretir. Bu testler
her dalı + _facts_sufficient şema mantığını doğrudan (graph/LLM olmadan) doğrular.
"""

from __future__ import annotations

from agents.policy import (
    CLARIFY_MARKER,
    MAX_CLARIFICATION_ROUNDS,
    MIN_FACTS_FOR_ANSWER,
    REQUIRED_FACTS,
    _facts_sufficient,
    decide_path,
)

# --- decide_path: intent passthrough ---

def test_smalltalk_intent_returns_smalltalk():
    assert decide_path({"response_intent": "smalltalk", "domain": "unknown"}) == "smalltalk"


def test_out_of_scope_sensitive_returns_reject_sensitive():
    state = {"response_intent": "out_of_scope_sensitive", "domain": "unknown"}
    assert decide_path(state) == "reject_sensitive"


def test_unknown_domain_returns_redirect():
    state = {"response_intent": "redirect_to_scope", "domain": "unknown"}
    assert decide_path(state) == "redirect"


# --- decide_path: clarify vs answer ---

def test_kira_with_no_facts_returns_clarify():
    state = {"response_intent": "legal_answer", "domain": "kira", "case_facts": {}}
    assert decide_path(state) == "clarify"


def test_kira_with_sufficient_facts_returns_answer():
    # kira: "olay" gerekli + en az 2 olgu.
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {"olay": "depozito iade edilmiyor", "tutar": "5000 TL"},
    }
    assert decide_path(state) == "answer"


def test_kira_with_only_one_fact_returns_clarify():
    # olay var ama tek olgu < MIN_FACTS_FOR_ANSWER["kira"]=2.
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {"olay": "depozito iade edilmiyor"},
    }
    assert decide_path(state) == "clarify"


def test_tuketici_with_single_fact_returns_answer():
    # tüketici min=1 → olay + 1 olgu yeterli.
    state = {
        "response_intent": "legal_answer",
        "domain": "tuketici",
        "case_facts": {"olay": "ayıplı ürün"},
    }
    assert decide_path(state) == "answer"


def test_missing_case_facts_key_treated_as_empty():
    # Genel-soru kalıbı yok + olgu yok → durumsal şikâyet kabul → clarify.
    state = {"response_intent": "legal_answer", "domain": "kira", "question": "depozitomu alamıyorum"}
    assert decide_path(state) == "clarify"


def test_general_question_answers_even_without_facts():
    # "nasıl hesaplanır?" gibi tanımsal bilgi sorusu olgu-yok olsa da cevaplanır.
    state = {
        "response_intent": "legal_answer",
        "domain": "isHukuku",
        "case_facts": {},
        "question": "Kıdem tazminatı nasıl hesaplanır?",
    }
    assert decide_path(state) == "answer"


def test_situational_complaint_without_facts_clarifies():
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {},
        "question": "kira depozitomu ev sahibi geri vermiyor",
    }
    assert decide_path(state) == "clarify"


# --- decide_path: loop guards ---

def test_round_at_limit_forces_answer():
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {},
        "clarification_round": MAX_CLARIFICATION_ROUNDS,
    }
    assert decide_path(state) == "answer"


def test_user_already_answered_marker_forces_answer():
    # Önceki asistan turu netleştirme sorusuysa (marker), bu tur cevaptır.
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {},
        "chat_history": [
            {"role": "user", "content": "depozitomu alamıyorum"},
            {"role": "assistant", "content": f"{CLARIFY_MARKER}\n\n1. Sözleşme bitti mi?"},
        ],
    }
    assert decide_path(state) == "answer"


def test_history_without_marker_does_not_force_answer():
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {},
        "chat_history": [
            {"role": "assistant", "content": "Merhaba, nasıl yardımcı olabilirim?"},
        ],
    }
    assert decide_path(state) == "clarify"


# --- _facts_sufficient unit ---

def test_facts_sufficient_requires_required_keys():
    # kira "olay" gerektirir; olay yoksa yetersiz.
    assert _facts_sufficient("kira", {"tutar": "5000", "tarih": "2026"}) is False


def test_facts_sufficient_respects_min_count():
    assert _facts_sufficient("kira", {"olay": "x"}) is False           # 1 < 2
    assert _facts_sufficient("kira", {"olay": "x", "sure": "1 yıl"}) is True


def test_facts_sufficient_ignores_blank_values():
    assert _facts_sufficient("tuketici", {"olay": "   "}) is False


def test_unknown_domain_in_schema_defaults_min_one():
    # Şemada olmayan domain → required boş, min 1 (savunmacı default).
    assert _facts_sufficient("xyz", {"olay": "bir olay"}) is True
    assert _facts_sufficient("xyz", {}) is False


# --- schema sanity ---

def test_all_valid_domains_have_schema_entries():
    domains = {"tuketici", "isHukuku", "kira", "icra", "trafik", "vergi", "tapu", "idari"}
    assert domains <= set(REQUIRED_FACTS)
    assert domains <= set(MIN_FACTS_FOR_ANSWER)
