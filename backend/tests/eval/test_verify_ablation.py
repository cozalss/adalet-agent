"""verify_ablation harness saf-mantık testleri (LLM/Qdrant gerektirmez).

Gerçek ON/OFF koşumu Qwen GPU ister; burada yalnız ölçüm çekirdeğini
(_summarize_arm / _aggregate / _claim_support) sentetik state'lerle doğrularız.
"""

from __future__ import annotations

from eval.verify_ablation import _aggregate, _claim_support, _summarize_arm


def _state(verdict, claims, dogrula="", resp_extra=""):
    """Sentetik graph final-state."""
    return {
        "debate_verdict": verdict,
        "verified_claims": claims,
        "confidence": 0.8,
        "response": f"Cevap. {dogrula} {resp_extra}".strip(),
    }


def test_claim_support_counts_verified():
    claims = [{"verified": True}, {"verified": False}, {"verified": True}]
    assert _claim_support({"verified_claims": claims}) == (2, 3)


def test_claim_support_empty():
    assert _claim_support({}) == (0, 0)


def test_summarize_arm_support_ratio_and_dogrula():
    s = _summarize_arm(_state("pass", [{"verified": True}, {"verified": False}],
                              dogrula="[DOĞRULA: madde no]"))
    assert s["verdict"] == "pass"
    assert s["n_claims"] == 2
    assert s["n_verified"] == 1
    assert s["support_ratio"] == 0.5
    assert s["n_dogrula"] == 1


def test_aggregate_block_rate_detects_verify_catch():
    """OFF pass iken ON reject → verify YAKALADI (block_rate'e sayılır)."""
    rows = [
        # verify yakaladı: OFF tüm claim supported+pass, ON reject
        {"id": "Q1", "question": "q",
         "on": _summarize_arm(_state("reject", [{"verified": False}])),
         "off": _summarize_arm(_state("pass", [{"verified": True}])),
         "verify_blocked": True},
        # verify etkisiz: ikisi de pass
        {"id": "Q2", "question": "q",
         "on": _summarize_arm(_state("pass", [{"verified": True}])),
         "off": _summarize_arm(_state("pass", [{"verified": True}])),
         "verify_blocked": False},
    ]
    agg = _aggregate(rows)
    assert agg["n"] == 2
    assert agg["n_blocked"] == 1
    assert agg["block_rate"] == 0.5
    # ON support ort = (0.0 + 1.0)/2 = 0.5 ; OFF = (1.0 + 1.0)/2 = 1.0 → Δ 0.5
    assert agg["avg_support_on"] == 0.5
    assert agg["avg_support_off"] == 1.0
    assert agg["support_delta"] == 0.5
    assert agg["verdicts_on"]["reject"] == 1
    assert agg["verdicts_off"]["pass"] == 2


def test_aggregate_skips_error_rows():
    rows = [
        {"id": "E1", "question": "q", "error": "boom"},
        {"id": "Q1", "question": "q",
         "on": _summarize_arm(_state("pass", [{"verified": True}])),
         "off": _summarize_arm(_state("pass", [{"verified": True}])),
         "verify_blocked": False},
    ]
    agg = _aggregate(rows)
    assert agg["n"] == 1  # error satırı sayılmaz


def test_aggregate_empty_returns_zero():
    assert _aggregate([{"id": "E", "question": "q", "error": "x"}]) == {"n": 0}
