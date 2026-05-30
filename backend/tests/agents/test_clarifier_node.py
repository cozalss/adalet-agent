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
