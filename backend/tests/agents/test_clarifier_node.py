"""clarifier_node — eksik bilgide sabit Türkçe takip soruları (LLM yok)."""

from __future__ import annotations

import pytest

from agents.nodes.clarifier import QUESTION_BANK, clarifier_node
from agents.policy import CLARIFY_MARKER


@pytest.mark.asyncio
async def test_kira_returns_clarification_intent_and_questions():
    out = await clarifier_node({"domain": "kira", "case_facts": {}})

    assert out["response_intent"] == "needs_clarification"
    questions = out["clarifying_questions"]
    assert isinstance(questions, list)
    assert 2 <= len(questions) <= 4


@pytest.mark.asyncio
async def test_clarify_response_contains_marker_and_questions():
    out = await clarifier_node({"domain": "kira", "case_facts": {}})

    body = out["clarify_response"]
    assert CLARIFY_MARKER in body
    # Sorular gövdede numaralı listelenmeli.
    assert "1." in body
    for q in out["clarifying_questions"]:
        assert q in body


@pytest.mark.asyncio
async def test_increments_clarification_round():
    out = await clarifier_node({"domain": "kira", "case_facts": {}})
    assert out["clarification_round"] == 1

    out2 = await clarifier_node({"domain": "kira", "case_facts": {}, "clarification_round": 1})
    assert out2["clarification_round"] == 2


@pytest.mark.asyncio
async def test_skips_questions_for_already_known_facts():
    # "olay" zaten biliniyorsa, o olguya bağlı soru tekrar sorulmamalı.
    known = await clarifier_node({"domain": "kira", "case_facts": {}})
    skipped = await clarifier_node({"domain": "kira", "case_facts": {"olay": "depozito iadesi"}})

    # olay-bağlı soru (banka'da ("olay", ...) ile etiketli) çıktıdan düşmeli.
    olay_question = next(q for key, q in QUESTION_BANK["kira"] if key == "olay")
    assert olay_question in known["clarifying_questions"]
    assert olay_question not in skipped["clarifying_questions"]
    # Yine de en az 2 soru kalmalı (banka'da etiketsiz sorular var).
    assert len(skipped["clarifying_questions"]) >= 2


@pytest.mark.asyncio
async def test_kira_eviction_asks_discriminating_reason_question():
    # Ev sahibi tahliye senaryosu → jenerik banka yerine ayırt edici SEBEP sorusu.
    out = await clarifier_node({
        "domain": "kira",
        "question": "kiracımı çıkaramıyorum",
        "case_facts": {"olay": "kiracıyı çıkaramıyorum"},
    })
    assert out["response_intent"] == "needs_clarification"
    joined = " ".join(out["clarifying_questions"]).lower()
    assert "sebep" in joined  # 'hangi sebeple çıkarmak istiyorsunuz'
    assert CLARIFY_MARKER in out["clarify_response"]


@pytest.mark.asyncio
async def test_kira_eviction_round1_emits_clickable_options():
    # Round-1 sebep-sorusunda tıklanabilir cevap-şıkları üretilir.
    out = await clarifier_node({
        "domain": "kira",
        "question": "kiracımı çıkaramıyorum",
        "case_facts": {"olay": "kiracıyı çıkaramıyorum"},
    })
    assert len(out["clarify_options"]) == 6


@pytest.mark.asyncio
async def test_kira_eviction_round2_has_no_options():
    # Sebep verildiyse (round-2 follow-up) şık yok — açık uçlu soru sorulur.
    out = await clarifier_node({
        "domain": "kira",
        "question": "kendi ihtiyacım için lazım",
        "case_facts": {"olay": "kiracıyı çıkaramıyorum kendi ihtiyacım için lazım"},
    })
    assert out["clarify_options"] == []


@pytest.mark.asyncio
async def test_kira_eviction_round2_asks_reason_specific_followup():
    # Sebep (ihtiyaç) verilmişse clarifier round-2 sebebe-özel soruyu üretir.
    out = await clarifier_node({
        "domain": "kira",
        "question": "kendi ihtiyacım için lazım",
        "case_facts": {"olay": "kiracıyı çıkaramıyorum kendi ihtiyacım için lazım"},
    })
    joined = " ".join(out["clarifying_questions"]).lower()
    assert "oturac" in joined or "sürekli" in joined  # ihtiyaç-özel follow-up


@pytest.mark.asyncio
async def test_kira_non_eviction_still_uses_generic_bank():
    # Tahliye DIŞI kira sorunu (depozito) → eski jenerik banka korunur (regresyon yok).
    out = await clarifier_node({
        "domain": "kira",
        "question": "depozitomu geri alamıyorum",
        "case_facts": {},
    })
    olay_question = next(q for key, q in QUESTION_BANK["kira"] if key == "olay")
    assert olay_question in out["clarifying_questions"]


@pytest.mark.asyncio
async def test_unsupported_domain_is_noop():
    # Banka'da olmayan/unknown domain → no-op; legal akışa düşer.
    out = await clarifier_node({"domain": "unknown", "case_facts": {}})
    assert out == {}


@pytest.mark.asyncio
async def test_question_bank_has_no_legal_claims():
    # Sıfır halüsinasyon: sorular madde/karar numarası içermemeli.
    import re

    for domain, pairs in QUESTION_BANK.items():
        for _key, question in pairs:
            assert not re.search(r"\bmadde\s*\d", question.lower()), domain
            assert "[src:" not in question
