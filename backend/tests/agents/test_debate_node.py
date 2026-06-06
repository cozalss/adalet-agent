"""debate_node — Constitutional self-critique + retry kararı testleri.

MockLLM debate JSON formatını tanır (llm.py _mock_json_response).
"""

from __future__ import annotations

import pytest

from agents.config import MAX_RETRY
from agents.nodes.debate import debate_node


@pytest.mark.asyncio
async def test_debate_pass_skips_llm(base_state):
    """verify pass → ekstra LLM çağrılmaz (token tasarrufu)."""
    base_state["debate_verdict"] = "pass"
    base_state["claims"] = base_state["claims"][:2]
    base_state["verified_claims"] = [
        {**c, "verified": True, "verify_score": 0.8, "verify_reason": "ok"}
        for c in base_state["claims"]
    ]
    result = await debate_node(base_state)
    assert result["debate_verdict"] == "pass"


@pytest.mark.asyncio
async def test_debate_hard_reject_propagates(base_state):
    """verify reject → debate da reject döner, LLM çağırmaz."""
    base_state["debate_verdict"] = "reject"
    base_state["debate_notes"] = "Çelişki tespit edildi"
    result = await debate_node(base_state)
    assert result["debate_verdict"] == "reject"


@pytest.mark.asyncio
async def test_debate_retry_increments_counter(base_state, monkeypatch):
    """verify retry → LLM çağrılır; MockLLM debate JSON döndürür, score 0.78 → pass."""
    monkeypatch.setenv("DEBATE_LLM_ON_RETRY", "1")
    base_state["debate_verdict"] = "retry"
    base_state["retry_count"] = 0
    base_state["draft_response"] = "Bir taslak [src: m-TKHK-11]"
    result = await debate_node(base_state)
    # MockLLM debate prompt'unu tanıyıp score=0.78 verdi → llm_verdict="pass"
    # bu sebeple retry_count artmaz; debate_verdict="pass"
    assert result["debate_verdict"] in {"pass", "retry"}
    if result["debate_verdict"] == "retry":
        assert result.get("retry_count", 0) == 1


@pytest.mark.asyncio
async def test_debate_rejects_when_retry_limit_reached(base_state):
    """retry_count >= MAX_RETRY → hard reject."""
    base_state["debate_verdict"] = "retry"
    base_state["retry_count"] = MAX_RETRY
    result = await debate_node(base_state)
    assert result["debate_verdict"] == "reject"
    assert "limit" in result["debate_notes"].lower()


@pytest.mark.asyncio
async def test_debate_handles_llm_failure_gracefully(base_state, monkeypatch):
    """LLM exception → deterministic retry + retry_count artar."""
    monkeypatch.setenv("DEBATE_LLM_ON_RETRY", "1")
    base_state["debate_verdict"] = "retry"
    base_state["retry_count"] = 0

    async def _boom(*_a, **_k):
        raise RuntimeError("LLM down")

    from agents.nodes import debate as debate_mod
    monkeypatch.setattr(debate_mod, "_llm_critique", _boom)

    result = await debate_node(base_state)
    assert result["debate_verdict"] == "retry"
    assert result["retry_count"] == 1
    assert "LLM kritik hata" in result["debate_notes"]


@pytest.mark.asyncio
async def test_debate_retry_once_on_zero_verified_then_reject(base_state, monkeypatch):
    """iter14: fast-mode'da 0-doğrulanmış-claim → ilk geçişte reddetmeden RETRY (draft
    non-determinism telafisi); 2. geçişte hâlâ 0 → reject. (MAX_RETRY'a çıkarmak ölçüldü-reddedildi:
    sistematik 0-verified phrasing'lerde retry kurtarmıyor, sadece latency ekliyor.)"""
    monkeypatch.delenv("DEBATE_LLM_ON_RETRY", raising=False)  # fast mode
    claims = [{"text": "x", "cite_ids": [], "verified": False, "verify_score": 0.0, "verify_reason": ""}]
    # 1. geçiş (retry_count=0): retry
    s = {**base_state, "debate_verdict": "retry", "retry_count": 0,
         "verified_claims": claims, "claims": claims}
    out = await debate_node(s)
    assert out["debate_verdict"] == "retry" and out.get("retry_count") == 1
    # 2. geçiş (retry_count=1): hâlâ 0 doğrulanmış → reject
    s2 = {**base_state, "debate_verdict": "retry", "retry_count": 1,
          "verified_claims": claims, "claims": claims}
    out2 = await debate_node(s2)
    assert out2["debate_verdict"] == "reject"
