"""Citation-grounding kontrolü (2.3) — 'correct ≠ faithful'.

Cited bir iddia FUZZY ile yüzeysel eşleşip (misgrounded) "supported" geçebiliyordu.
CITE_GROUNDING_CHECK açıkken cited iddialar için fuzzy TEK BAŞINA yetmez; cite hedefi
gerçekten temellendirmeli (lettuce/NLI entailment). Opt-in (default 0) → baseline korunur.
CLATTER (2.1) ile zincirlenir. SOTA: RAGAS faithfulness / Stanford-2024 misgrounded citation.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agents.nodes.verify import verify_node
from agents.state import Claim


@dataclass
class _FakeNLIResult:
    label: str
    score: float
    entailment_score: float
    neutral_score: float
    contradiction_score: float


class _FakeVerifier:
    def __init__(self, contradiction: float = 0.05, entailment: float = 0.7) -> None:
        self.contradiction = contradiction
        self.entailment = entailment

    def verify_batch(self, pairs, batch_size=16):
        return [
            _FakeNLIResult(
                label="entailment" if self.entailment > self.contradiction else "contradiction",
                score=max(self.entailment, self.contradiction),
                entailment_score=self.entailment,
                neutral_score=max(0.0, 1.0 - self.entailment - self.contradiction),
                contradiction_score=self.contradiction,
            )
            for _ in pairs
        ]


_CITED_CLAIM = Claim(
    text=(
        "Tüketici ayıplı malda sözleşmeden dönme veya bedel indirimi "
        "talep edebilir [src: m-TKHK-11]"
    ),
    cite_ids=["m-TKHK-11"],
    verified=False, verify_score=0.0, verify_reason="",
)
_UNCITED_CLAIM = Claim(
    text="Tüketici ayıplı malda sözleşmeden dönme veya bedel indirimi talep edebilir",
    cite_ids=[],
    verified=False, verify_score=0.0, verify_reason="",
)


@pytest.mark.asyncio
async def test_cite_check_off_fuzzy_supports_cited(base_state, monkeypatch):
    """Default (kapalı): cited iddia fuzzy ile destekli sayılır → pass. Regresyon koruması."""
    monkeypatch.delenv("CITE_GROUNDING_CHECK", raising=False)
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.30),  # NLI neutral
        raising=False,
    )
    base_state["claims"] = [_CITED_CLAIM]
    base_state["retry_count"] = 0
    result = await verify_node(base_state)
    assert result["debate_verdict"] == "pass"


@pytest.mark.asyncio
async def test_cite_check_on_demotes_fuzzy_only_cited(base_state, monkeypatch):
    """Açık: cited iddia fuzzy-high AMA NLI neutral → fuzzy yetmez → unsupported → retry.
    Misgrounded citation (yüzeysel örtüşme) yakalanır."""
    monkeypatch.setenv("CITE_GROUNDING_CHECK", "1")
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.30),
        raising=False,
    )
    base_state["claims"] = [_CITED_CLAIM]
    base_state["retry_count"] = 0
    result = await verify_node(base_state)
    assert result["debate_verdict"] == "retry"  # 0/1 supported → retry (hak var)


@pytest.mark.asyncio
async def test_cite_check_on_passes_when_entailed(base_state, monkeypatch):
    """Açık: cited iddia NLI entailment alıyorsa (gerçek grounding) → supported → pass."""
    monkeypatch.setenv("CITE_GROUNDING_CHECK", "1")
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.80),
        raising=False,
    )
    base_state["claims"] = [_CITED_CLAIM]
    base_state["retry_count"] = 0
    result = await verify_node(base_state)
    assert result["debate_verdict"] == "pass"


@pytest.mark.asyncio
async def test_cite_check_on_uncited_claim_unaffected(base_state, monkeypatch):
    """Açık ama iddia cite TAŞIMIYOR → kapı uygulanmaz, fuzzy destek korunur → pass."""
    monkeypatch.setenv("CITE_GROUNDING_CHECK", "1")
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.30),
        raising=False,
    )
    base_state["claims"] = [_UNCITED_CLAIM]
    base_state["retry_count"] = 0
    result = await verify_node(base_state)
    assert result["debate_verdict"] == "pass"
