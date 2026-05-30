"""finalize_node — fail-closed ama kapsam-koruyan cümle-eleme testleri."""

from __future__ import annotations

import pytest

from agents.nodes.finalize import _split_sentences, finalize_node


def _asciiish(text: str) -> str:
    return text.translate(str.maketrans({
        "ç": "c", "Ç": "C",
        "ğ": "g", "Ğ": "G",
        "ı": "i", "I": "I",
        "İ": "I", "i": "i",
        "ö": "o", "Ö": "O",
        "ş": "s", "Ş": "S",
        "ü": "u", "Ü": "U",
    })).lower()


@pytest.mark.asyncio
async def test_finalize_strips_unverified_keeps_verified(base_state):
    """Bazı claim'ler doğrulanmamışsa: tüm cevap reddedilmez — doğrulanmamış
    cümle ATILIR, doğrulanmış cümle KORUNUR (kapsam-koruyan fail-closed)."""
    claims = [
        {
            "text": "Destekli iddia cümlesi yeterince uzun olmalı burada",
            "cite_ids": ["m-TKHK-11"],
            "verified": False, "verify_score": 0.0, "verify_reason": "",
        },
        {
            "text": "Desteksiz uydurma iddia cümlesi de yeterince uzun olmalı",
            "cite_ids": [],
            "verified": False, "verify_score": 0.0, "verify_reason": "",
        },
    ]
    verified_claims = [
        {**claims[0], "verified": True, "verify_score": 0.9, "verify_reason": "ok"},
        {**claims[1], "verified": False, "verify_score": 0.1, "verify_reason": "Yetersiz kanıt"},
    ]
    state = {
        **base_state,
        "draft_response": (
            "Destekli iddia cümlesi yeterince uzun olmalı burada. "
            "Desteksiz uydurma iddia cümlesi de yeterince uzun olmalı."
        ),
        "claims": claims,
        "verified_claims": verified_claims,
        "debate_verdict": "pass",
    }

    out = await finalize_node(state)

    # Cevap reddedilmedi (kapsam korundu) ama doğrulanmamış cümle atıldı.
    assert out["confidence"] > 0.0
    assert "Destekli iddia cümlesi" in out["response"]
    assert "Desteksiz uydurma iddia" not in out["response"]


@pytest.mark.asyncio
async def test_finalize_emits_clarify_response_directly():
    """needs_clarification: hazır takip soruları doğrudan basılır — hukuki
    assembly/disclaimer YOK, reject yoluna düşmez (domain geçerli olsa bile)."""
    clarify = (
        "Daha doğru yardımcı olabilmem için birkaç bilgiye ihtiyacım var:\n\n"
        "1. Kira sözleşmesi sona erdi mi?\n2. Evi teslim ettiniz mi?"
    )
    state = {
        "domain": "kira",
        "debate_verdict": "pass",
        "response_intent": "needs_clarification",
        "clarify_response": clarify,
        "clarifying_questions": ["Kira sözleşmesi sona erdi mi?", "Evi teslim ettiniz mi?"],
    }

    out = await finalize_node(state)

    assert out["response"] == clarify
    assert out["disclaimers"] == []
    assert out["confidence"] == 0.0
    assert "Kaynaklar" not in out["response"]


@pytest.mark.asyncio
async def test_finalize_rejects_when_all_claims_unverified(base_state):
    """Hiçbir iddia doğrulanmadıysa gösterilecek güvenli içerik yok → reddet."""
    claims = [
        {
            "text": "Doğrulanamayan tek iddia cümlesi yeterince uzun",
            "cite_ids": [], "verified": False, "verify_score": 0.0, "verify_reason": "",
        },
    ]
    verified_claims = [
        {**claims[0], "verified": False, "verify_score": 0.1, "verify_reason": "Yetersiz kanıt"},
    ]
    state = {
        **base_state,
        "draft_response": "Doğrulanamayan tek iddia cümlesi yeterince uzun.",
        "claims": claims,
        "verified_claims": verified_claims,
        "debate_verdict": "pass",
    }

    out = await finalize_node(state)

    assert out["debate_verdict"] == "reject"
    assert out["confidence"] == 0.0
    assert "Bu soruya şu an net bir yanıt veremiyorum" in out["response"]


@pytest.mark.asyncio
async def test_finalize_unknown_domain_redirects_to_scope_without_disclaimer(base_state):
    state = {
        **base_state,
        "question": "Film onerir misin?",
        "domain": "unknown",
        "domain_confidence": 0.0,
        "triage_reasoning": "Kapsam disi genel soru",
    }

    out = await finalize_node(state)

    assert out["debate_verdict"] == "reject"
    assert out["confidence"] == 0.0
    assert out["disclaimers"] == []
    response = _asciiish(out["response"])
    assert "guvenilir bir cevap verecek sekilde tasarlanmadim" in response
    assert "benim ana amacim" in response
    assert "hukuki durumu" in response


@pytest.mark.asyncio
async def test_finalize_drops_mixed_sentence_instead_of_leaking_unverified(base_state):
    """Aynı cümlede destekli + desteksiz iddia varsa parçalayamayız; cümle atılır."""
    claims = [
        {
            "text": "Destekli iddia bu cümlede geçiyor",
            "cite_ids": ["m-TKHK-11"],
            "verified": False,
            "verify_score": 0.0,
            "verify_reason": "",
        },
        {
            "text": "desteksiz uydurma iddia da aynı cümlede geçiyor",
            "cite_ids": [],
            "verified": False,
            "verify_score": 0.0,
            "verify_reason": "",
        },
    ]
    verified_claims = [
        {**claims[0], "verified": True, "verify_score": 0.9, "verify_reason": "ok"},
        {**claims[1], "verified": False, "verify_score": 0.1, "verify_reason": "Yetersiz kanıt"},
    ]
    state = {
        **base_state,
        "draft_response": (
            "Destekli iddia bu cümlede geçiyor ve desteksiz uydurma iddia da "
            "aynı cümlede geçiyor."
        ),
        "claims": claims,
        "verified_claims": verified_claims,
        "debate_verdict": "pass",
    }

    out = await finalize_node(state)

    assert out["debate_verdict"] == "reject"
    assert "desteksiz uydurma iddia" not in out["response"]


@pytest.mark.asyncio
async def test_finalize_treats_missing_verified_claim_as_unverified(base_state):
    """verify sonucu eksik dönerse eksik claim güvenli tarafta doğrulanmamış sayılır."""
    claims = [
        {
            "text": "Destekli iddia cümlesi burada kalmalı",
            "cite_ids": ["m-TKHK-11"],
            "verified": False,
            "verify_score": 0.0,
            "verify_reason": "",
        },
        {
            "text": "Eksik verify sonucu olan iddia burada atılmalı",
            "cite_ids": [],
            "verified": False,
            "verify_score": 0.0,
            "verify_reason": "",
        },
    ]
    verified_claims = [
        {**claims[0], "verified": True, "verify_score": 0.9, "verify_reason": "ok"},
    ]
    state = {
        **base_state,
        "draft_response": (
            "Destekli iddia cümlesi burada kalmalı. "
            "Eksik verify sonucu olan iddia burada atılmalı."
        ),
        "claims": claims,
        "verified_claims": verified_claims,
        "debate_verdict": "pass",
    }

    out = await finalize_node(state)

    assert out["confidence"] > 0.0
    assert "Destekli iddia cümlesi" in out["response"]
    assert "Eksik verify sonucu" not in out["response"]


def test_split_sentences_keeps_madde_abbreviation_together():
    text = "TKHK m. 11 tüketiciye seçimlik hak verir. ayrıca bu ayrı cümledir."

    out = _split_sentences(text)

    assert out == [
        "TKHK m. 11 tüketiciye seçimlik hak verir.",
        "ayrıca bu ayrı cümledir.",
    ]


@pytest.mark.asyncio
async def test_finalize_passes_when_all_claims_verified(base_state):
    claims = [
        {
            "text": "Tüketici ayıplı malda sözleşmeden dönebilir",
            "cite_ids": ["m-TKHK-11"],
            "verified": False,
            "verify_score": 0.0,
            "verify_reason": "",
        },
    ]
    verified_claims = [
        {**claims[0], "verified": True, "verify_score": 0.9, "verify_reason": "Fuzzy 0.90"},
    ]
    state = {
        **base_state,
        "draft_response": "Tüketici ayıplı malda sözleşmeden dönebilir [src: m-TKHK-11].",
        "claims": claims,
        "verified_claims": verified_claims,
        "debate_verdict": "pass",
    }

    out = await finalize_node(state)

    assert out["confidence"] > 0.0
    assert "Tüketici ayıplı malda" in out["response"]
    assert "Kaynaklar" in out["response"]


@pytest.mark.asyncio
async def test_finalize_rejects_retry_verdict(base_state):
    state = {**base_state, "debate_verdict": "retry", "debate_notes": "Retry limiti doldu"}

    out = await finalize_node(state)

    assert out["debate_verdict"] == "reject"
    assert out["confidence"] == 0.0
    assert "Bu konuda güvenilir bir yanıt oluşturmayı birkaç kez denedim" in out["response"]
