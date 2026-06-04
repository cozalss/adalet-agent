"""CLATTER entailment kapısı (2.1) — yüksek-riskli uygunluk iddialarında neutral=desteklenmedi.

Kök sorun: verify L3 yalnız contradiction-veto; "neutral" (kaynak ne onaylıyor ne
çürütüyor) iddialar fuzzy>=0.45 ile "supported" sayılıp MIN_VERIFIED_CLAIMS_RATIO=0.20
kapısından geçebiliyor. Süre/eşik gerekçeli uygunluk SONUCU ("2 yıl → kıdem alabilirsiniz"
/ "2 yıl → yetersiz") bu delikten kaçan çıkarım-halüsinasyonunun en tehlikeli sınıfı.
Fuzzy bu iddialarda doğru-yanlış çıkarımı ayırt EDEMEZ → CLATTER kapısı POZİTİF NLI
entailment ister.

Kapı OPT-IN (CLATTER_GATE_ENABLED, default 0): yalnız pass→retry/reject yönünde
SIKILAŞTIRIR; default davranış (1189-test baseline) birebir korunur.
SOTA: CLATTER arXiv 2506.05243 — neutral=not-supported → attribution 0.72→0.97.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agents.nodes.verify import verify_node
from agents.risk_guard import is_high_risk_eligibility_claim
from agents.state import Claim

# --------------------------------------------------------------------------
# Detektör: is_high_risk_eligibility_claim (süre/eşik + uygunluk sonucu)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "2 yıl çalıştıysanız kıdem tazminatına hak kazanırsınız",   # pozitif + süre
        "İki yıl çalışınca kıdem tazminatı alabilirsiniz",          # yazıyla süre + pozitif
        "2 yıl süre yetersiz olduğundan tazminat alamazsınız",      # negatif + süre
        "1 yılın altında kıdem doğmaz",                             # negatif eşik
        "5.000 TL altındaki uyuşmazlıkta hakem heyetine başvurabilirsiniz",  # para eşiği + pozitif
    ],
)
def test_high_risk_eligibility_detected(text: str) -> None:
    assert is_high_risk_eligibility_claim(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Ayıplı malda iade hakkınız bulunmaktadır",        # uygunluk var ama süre/eşik YOK
        "Kira sözleşmesi yazılı veya sözlü yapılabilir",   # ne süre ne sonuç
        "Tüketici hakem heyetine başvurabilir",            # eşik YOK → dar detektör
        "İşveren ücreti ayda bir ödemekle yükümlüdür",     # işveren yükümlülüğü, hak-sonucu değil
    ],
)
def test_non_high_risk_not_detected(text: str) -> None:
    assert is_high_risk_eligibility_claim(text) is False


# --------------------------------------------------------------------------
# verify_node CLATTER kapısı — NLI mock'lu entegrasyon
# --------------------------------------------------------------------------


@dataclass
class _FakeNLIResult:
    label: str
    score: float
    entailment_score: float
    neutral_score: float
    contradiction_score: float


class _FakeVerifier:
    """Tüm çiftlere sabit (entailment, contradiction) döndüren NLI mock."""

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


def _state_with_highrisk(base_state: dict) -> dict:
    """base_state'i: 1 desteklenen normal claim + 1 yüksek-riskli uygunluk claim'i
    ile kur. Normal claim fuzzy ile destekli (ratio>=0.20 → base 'pass'); yüksek-riskli
    claim entailment'a bağlı (CLATTER'ın tetiklenip tetiklenmeyeceğini belirler)."""
    base_state["claims"] = [
        Claim(
            text=(
                "Tüketici ayıplı malda sözleşmeden dönme veya bedel indirimi "
                "talep edebilir [src: m-TKHK-11]"
            ),
            cite_ids=["m-TKHK-11"],
            verified=False, verify_score=0.0, verify_reason="",
        ),
        Claim(
            text="2 yıl çalıştıysanız kıdem tazminatına hak kazanırsınız [src: m-IK-32]",
            cite_ids=["m-IK-32"],
            verified=False, verify_score=0.0, verify_reason="",
        ),
    ]
    base_state["draft_response"] = "Mock taslak [src: m-TKHK-11]"
    base_state["retry_count"] = 0
    return base_state


@pytest.mark.asyncio
async def test_clatter_off_passes_unentailed_highrisk(base_state, monkeypatch):
    """CLATTER kapalı (default): yüksek-riskli claim entailment'sız olsa bile baseline
    davranış → pass (ratio>=0.20). Regresyon koruması."""
    monkeypatch.delenv("CLATTER_GATE_ENABLED", raising=False)
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.30),  # entailment YOK
        raising=False,
    )
    state = _state_with_highrisk(base_state)
    result = await verify_node(state)
    assert result["debate_verdict"] == "pass"


@pytest.mark.asyncio
async def test_clatter_on_blocks_unentailed_highrisk(base_state, monkeypatch):
    """CLATTER açık: yüksek-riskli claim POZİTİF entailment alamıyorsa pass ENGELLENİR
    → retry (retry hakkı var). Çıkarım-halüsinasyon deliği kapanır."""
    monkeypatch.setenv("CLATTER_GATE_ENABLED", "1")
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.30),  # entailment YOK
        raising=False,
    )
    state = _state_with_highrisk(base_state)
    result = await verify_node(state)
    assert result["debate_verdict"] == "retry"
    assert "CLATTER" in result["debate_notes"]


@pytest.mark.asyncio
async def test_clatter_on_passes_entailed_highrisk(base_state, monkeypatch):
    """CLATTER açık: yüksek-riskli claim POZİTİF entailment alıyorsa → pass (engel yok)."""
    monkeypatch.setenv("CLATTER_GATE_ENABLED", "1")
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.80),  # entailment VAR
        raising=False,
    )
    state = _state_with_highrisk(base_state)
    result = await verify_node(state)
    assert result["debate_verdict"] == "pass"


@pytest.mark.asyncio
async def test_clatter_on_inert_without_highrisk(base_state, sample_claims, monkeypatch):
    """CLATTER açık ama yüksek-riskli (süre/eşik) iddia YOK → kapı no-op, pass korunur."""
    monkeypatch.setenv("CLATTER_GATE_ENABLED", "1")
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.30),
        raising=False,
    )
    base_state["claims"] = sample_claims[:2]  # süre/eşik içermez
    base_state["retry_count"] = 0
    result = await verify_node(base_state)
    assert result["debate_verdict"] == "pass"
    assert "CLATTER" not in result["debate_notes"]


@pytest.mark.asyncio
async def test_clatter_on_rejects_when_retry_exhausted(base_state, monkeypatch):
    """CLATTER açık + retry hakkı bitti → unentailed yüksek-riskli claim reject."""
    monkeypatch.setenv("CLATTER_GATE_ENABLED", "1")
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.30),
        raising=False,
    )
    state = _state_with_highrisk(base_state)
    state["retry_count"] = 3  # MAX_RETRY
    result = await verify_node(state)
    assert result["debate_verdict"] == "reject"
    assert "CLATTER" in result["debate_notes"]
