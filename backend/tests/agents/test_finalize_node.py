"""finalize_node — fail-closed ama kapsam-koruyan cümle-eleme testleri."""

from __future__ import annotations

import pytest

from agents.nodes.finalize import finalize_node


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
    assert "Yetersiz kanıt" in out["response"]


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
    assert "Retry limiti doldu" in out["response"]
