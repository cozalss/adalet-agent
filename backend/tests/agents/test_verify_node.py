"""verify_node — 3 katmanlı verifier birim testleri.

Test stratejisi: NLI modeli pahalı (PyTorch + indirme), bu yüzden monkeypatch
ile verifier.nli.get_verifier'ı mock'lıyoruz. Katman 1 (rules) ve katman 2
(fuzzy) saf Python — gerçek.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agents.config import (
    FUZZY_SUPPORT_THRESHOLD,
)
from agents.nodes.verify import (
    _layer1_rules,
    _layer2_fuzzy,
    _verdict_from_ratio,
    verify_node,
)
from agents.state import Claim

# --------------------------------------------------------------------------
# Katman 1: rules
# --------------------------------------------------------------------------


def test_layer1_passes_when_no_madde_reference():
    claim = Claim(
        text="Tüketici ayıplı malda iade hakkına sahiptir.",
        cite_ids=[], verified=False, verify_score=0.0, verify_reason="",
    )
    ok, msg = _layer1_rules(claim)
    assert ok is True
    assert msg == "ok"


def test_layer1_passes_with_valid_madde_format():
    claim = Claim(
        text="TKHK Madde 11'e göre ayıplı mal iadesi yapılır.",
        cite_ids=[], verified=False, verify_score=0.0, verify_reason="",
    )
    ok, _msg = _layer1_rules(claim)
    assert ok is True


def test_layer1_fails_when_madde_word_without_number():
    claim = Claim(
        text="İlgili maddede tüketici hakları açıkça belirtilmiştir.",
        cite_ids=[], verified=False, verify_score=0.0, verify_reason="",
    )
    ok, msg = _layer1_rules(claim)
    assert ok is False
    assert "numara format" in msg


def test_layer1_fails_with_out_of_range_madde():
    # Format geçerli ama parse_citation tarafından düşen kanun + madde
    claim = Claim(
        text="TKHK m. 999999 uyarınca tazminat verilir.",
        cite_ids=[], verified=False, verify_score=0.0, verify_reason="",
    )
    ok, _msg = _layer1_rules(claim)
    # 999999 > 99999 → format geçersiz
    assert ok is False


# --------------------------------------------------------------------------
# Katman 2: fuzzy
# --------------------------------------------------------------------------


def test_layer2_fuzzy_high_when_snippet_overlaps(sample_citations):
    claim = Claim(
        text="Tüketici ayıplı mal nedeniyle sözleşmeden dönme talep edebilir.",
        cite_ids=["m-TKHK-11"],
        verified=False, verify_score=0.0, verify_reason="",
    )
    score, _msg, idx = _layer2_fuzzy(claim, sample_citations)
    assert score >= FUZZY_SUPPORT_THRESHOLD
    assert idx >= 0


def test_layer2_fuzzy_low_when_claim_unrelated(sample_citations):
    claim = Claim(
        text="Bu metin tamamen farklı bir konuyu açıklayan rasgele cümledir.",
        cite_ids=[],
        verified=False, verify_score=0.0, verify_reason="",
    )
    score, _msg, _idx = _layer2_fuzzy(claim, sample_citations)
    assert score < FUZZY_SUPPORT_THRESHOLD


def test_layer2_empty_claim_returns_zero(sample_citations):
    claim = Claim(
        text="", cite_ids=[],
        verified=False, verify_score=0.0, verify_reason="",
    )
    score, _msg, idx = _layer2_fuzzy(claim, sample_citations)
    assert score == 0.0
    assert idx == -1


# --------------------------------------------------------------------------
# Verdict aggregation — ratio-based (v10 refactor)
# --------------------------------------------------------------------------
#
# v9 ölçümünde bulgu: tek NLI contradiction tüm cevabı reddediyordu (E3:
# 3/4 supported %75 ama 1 contradiction → reject). Türkçe XNLI 0.50-0.70
# contradiction skoru sık üretiyor (false-positive). v10 ratio-based ile:
#   - contradictions / n_total >= 0.5 → reject (gerçek çoğunluk yalan)
#   - 1 izole contradiction artık pass'i bozmaz (n_supported yüksekse pass)
# Bu testler regression koruması: ratio mantığı kazara veto'ya geri dönmesin.


def test_verdict_pass_when_majority_supported(base_state):
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(2, 3, base_state, contradictions=0)
    assert v == "pass"


def test_verdict_retry_when_low_support_under_limit(base_state):
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(0, 5, base_state, contradictions=0)
    assert v == "retry"


def test_verdict_reject_when_retry_limit_reached(base_state):
    base_state["retry_count"] = 3
    v = _verdict_from_ratio(0, 5, base_state, contradictions=0)
    assert v == "reject"


def test_verdict_zero_total_rejects(base_state):
    """Claim yoksa hiçbir şey doğrulanamaz → reject."""
    v = _verdict_from_ratio(0, 0, base_state, contradictions=0)
    assert v == "reject"


# --------------------------------------------------------------------------
# v10 ratio-based: izole contradiction artık pass'i bozmuyor
# --------------------------------------------------------------------------


def test_verdict_isolated_contradiction_does_not_block_pass(base_state):
    """1/5 contradiction (20% < 50%) AND support >= ratio threshold → pass.

    E3 (v9) regression: 3/4 supported + 1 contradiction was reject (NLI veto).
    v10 fix: ratio-based, izole contradiction artık reject yapmaz.
    """
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(4, 5, base_state, contradictions=1)
    assert v == "pass"


def test_verdict_half_contradiction_at_n4_does_not_reject(base_state):
    """n=4, c=2 (tam %50) — süpermajority eşiği floor(4/2)+1=3 talep eder.
    2 yetersiz → veto tetiklenmez (yarı yarıya = belirsiz, false-pos riski)."""
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(2, 4, base_state, contradictions=2)
    # supported=2/4=0.5 > MIN_RATIO (0.20) → pass
    assert v == "pass"


def test_verdict_three_of_four_contradiction_rejects(base_state):
    """n=4, c=3 (%75) — süpermajority eşiği 3 karşılandı → reject."""
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(1, 4, base_state, contradictions=3)
    assert v == "reject"


def test_verdict_all_contradictions_rejects(base_state):
    """contradictions = n_total → reject (her şey yalan)."""
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(0, 3, base_state, contradictions=3)
    assert v == "reject"


def test_verdict_contradiction_ratio_just_under_half_passes(base_state):
    """1/3 = 0.33 < 0.5 → contradiction reject tetiklenmez; support pass yapar."""
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(2, 3, base_state, contradictions=1)
    assert v == "pass"


# --- Small-n sinyal-redundans guard: tek çelişki kira-tipi false-positive'i ---

def test_verdict_single_contradiction_at_n2_does_not_reject(base_state):
    """Kira e2e regresyonu: 1/2 çelişki Türkçe-XNLI false-positive olabilir;
    tek çelişki sinyal redundansı koşulunu (>=2) karşılamaz → reject etmemeli.
    Supported 1/2 = %50 ≥ MIN_RATIO (0.20) → pass."""
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(1, 2, base_state, contradictions=1)
    assert v == "pass"


def test_verdict_two_contradictions_at_n2_still_rejects(base_state):
    """2/2 çelişki: hem ≥2 hem ratio=1.0 → redundans var, reject."""
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(0, 2, base_state, contradictions=2)
    assert v == "reject"


def test_verdict_single_contradiction_at_n1_falls_through(base_state):
    """n=1, 1 çelişki: tek çelişki veto yapamaz; 0 supported → retry (limit altında)."""
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(0, 1, base_state, contradictions=1)
    assert v == "retry"


def test_verdict_half_contradictions_at_n6_does_not_reject(base_state):
    """is-03 regresyonu: 3/6 çelişki = %50 yarı yarıya; süpermajority kuralı
    floor(6/2)+1 = 4 talep eder, 3 yetersiz → veto tetiklenmez.
    Supported 1/6 = %17 < MIN_RATIO (0.20) → retry (debate yeniden dener)."""
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(1, 6, base_state, contradictions=3)
    assert v == "retry"


def test_verdict_supermajority_contradictions_at_n6_rejects(base_state):
    """n=6, 4 çelişki: floor(6/2)+1=4 eşiği karşılar → reject."""
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(1, 6, base_state, contradictions=4)
    assert v == "reject"


def test_verdict_supermajority_at_n4(base_state):
    """n=4, 3 çelişki (75%): floor(4/2)+1=3 → reject; 2 çelişki → not."""
    base_state["retry_count"] = 0
    assert _verdict_from_ratio(1, 4, base_state, contradictions=3) == "reject"
    assert _verdict_from_ratio(3, 4, base_state, contradictions=2) == "pass"


def test_verdict_min_ratio_threshold_boundary(base_state):
    """MIN_VERIFIED_CLAIMS_RATIO sınırı (0.20) — 1/5 == 0.20 → pass."""
    from agents.config import MIN_VERIFIED_CLAIMS_RATIO
    assert MIN_VERIFIED_CLAIMS_RATIO == 0.20  # regression: eşik değişmemeli
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(1, 5, base_state, contradictions=0)
    assert v == "pass"


def test_verdict_below_min_ratio_retries_under_limit(base_state):
    """0/4 (0% < 20%) + retry hakkı var → retry, reject değil."""
    base_state["retry_count"] = 1
    v = _verdict_from_ratio(0, 4, base_state, contradictions=0)
    assert v == "retry"


def test_verdict_strong_contradiction_overrides_support(base_state):
    """Süpermajority çelişki support'u devirmeli — n=4 c=3 sup=3 → reject.

    Önceki kural (ratio>=0.5) n=4 c=2 sup=3 → reject diyordu (false-pos riski).
    Yeni süpermajority kuralı sadece "yarıdan FAZLA" tetikler: c=3 (75%) gerek.
    """
    base_state["retry_count"] = 0
    v = _verdict_from_ratio(3, 4, base_state, contradictions=3)
    assert v == "reject"


# --------------------------------------------------------------------------
# verify_node — full integration (NLI mock'lu)
# --------------------------------------------------------------------------


@dataclass
class _FakeNLIResult:
    label: str
    score: float
    entailment_score: float
    neutral_score: float
    contradiction_score: float


class _FakeVerifier:
    """NLI verifier mock — sabit cevap. Test izolasyonu için."""

    def __init__(self, contradiction: float = 0.0, entailment: float = 0.4):
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


@pytest.mark.asyncio
async def test_verify_node_returns_pass_for_supported_claims(
    base_state, sample_claims, monkeypatch,
):
    # NLI: hiç çelişki yok
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.7),
        raising=False,
    )
    # Sadece ilk 2 desteklenen claim'i kullan (3'üncü "TKHK m.999" uydurma)
    base_state["claims"] = sample_claims[:2]
    result = await verify_node(base_state)
    assert "verified_claims" in result
    assert result["debate_verdict"] in {"pass", "retry"}
    # En az 1 verified olmalı (fuzzy match TKHK m.11 üzerinden)
    n_verified = sum(1 for c in result["verified_claims"] if c["verified"])
    assert n_verified >= 1


@pytest.mark.asyncio
async def test_verify_node_rejects_on_contradiction(
    base_state, sample_claims, monkeypatch,
):
    # NLI: kesin çelişki (uydurma madde)
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.85, entailment=0.05),
        raising=False,
    )
    base_state["claims"] = sample_claims  # 3 claim, hepsine contradiction
    result = await verify_node(base_state)
    assert result["debate_verdict"] == "reject"
    assert "çelişki" in result["debate_notes"].lower()


@pytest.mark.asyncio
async def test_verify_node_risk_veto_rejects_hallucinated_draft(
    base_state, sample_claims, monkeypatch,
):
    """SIFIR HALÜSİNASYON: draft'ta süre-reddi/uydurma kanun varsa NLI temiz
    olsa bile verdict reject (risk veto). Gerçek regresyon vakası."""
    # NLI hiç çelişki bulmuyor (claim'ler [src:]-etiketli, fuzzy/NLI geçiyor) —
    # veto olmasa "pass" olurdu. Veto draft metnindeki yanlış-çıkarımı yakalamalı.
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.7),
        raising=False,
    )
    base_state["claims"] = sample_claims[:2]
    base_state["draft_response"] = (
        "Kısa cevap: Belirttiğiniz 2 yıl süre, kanunlarda belirtilen minimum "
        "çalışma süresini karşılamıyor [src: m-IK-21]. "
        "İşçilik Kanunu'nun 21. maddesi uyarınca bu süre 5 yılın altında ise "
        "tazminat verilmeyebilir [src: m-EIK-14]."
    )
    result = await verify_node(base_state)
    assert result["debate_verdict"] == "reject"
    assert "RİSK-VETO" in result["debate_notes"]


@pytest.mark.asyncio
async def test_verify_node_no_veto_for_clean_draft(
    base_state, sample_claims, monkeypatch,
):
    """Temiz draft'ta veto tetiklenmemeli — false-positive guard."""
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: _FakeVerifier(contradiction=0.05, entailment=0.7),
        raising=False,
    )
    base_state["claims"] = sample_claims[:2]
    base_state["draft_response"] = (
        "Kısa cevap: Ayıplı malda iade hakkınız bulunmaktadır [src: m-TKHK-11]."
    )
    result = await verify_node(base_state)
    assert "RİSK-VETO" not in result["debate_notes"]


@pytest.mark.asyncio
async def test_verify_node_handles_empty_claims(base_state):
    base_state["claims"] = []
    result = await verify_node(base_state)
    assert result["verified_claims"] == []
    # Hiç claim yok → ratio 0 → retry sayacı 0 → retry değil reject (claims=0)
    assert result["debate_verdict"] in {"reject", "retry"}


@pytest.mark.asyncio
async def test_verify_node_rejects_when_no_refs(base_state, sample_claims):
    base_state["claims"] = sample_claims
    base_state["mevzuat_refs"] = []
    base_state["emsal_refs"] = []
    result = await verify_node(base_state)
    assert result["debate_verdict"] == "reject"
    assert all(not c["verified"] for c in result["verified_claims"])


@pytest.mark.asyncio
async def test_verify_node_skips_nli_gracefully_when_unavailable(
    base_state, sample_claims, monkeypatch,
):
    """NLI yüklenemezse (ör. transformers eksik) verify yine çalışır."""
    def _boom():
        raise RuntimeError("torch yok")
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier", _boom, raising=False,
    )
    base_state["claims"] = sample_claims[:2]
    result = await verify_node(base_state)
    assert "verified_claims" in result
    # NLI yokken contradiction tespit edilemez ama fuzzy hâlâ çalışır
    assert len(result["verified_claims"]) == 2


class _PerClaimFakeVerifier:
    """NLI mock — claim sırasına göre farklı sonuç döndürür.

    İzole contradiction senaryosunu test etmek için: ilk claim contradict,
    sonrakiler entail. v10 ratio-based mantık 1/3 contradiction'ı reject
    yapmamalı (33% < 50%).
    """

    def __init__(self, results: list[tuple[float, float]]):
        # [(entailment, contradiction), ...]
        self.results = results

    def verify_batch(self, pairs, batch_size=16):
        out = []
        for i, _pair in enumerate(pairs):
            ent, con = self.results[i] if i < len(self.results) else (0.4, 0.05)
            label = "entailment" if ent > con else "contradiction"
            out.append(_FakeNLIResult(
                label=label,
                score=max(ent, con),
                entailment_score=ent,
                neutral_score=max(0.0, 1.0 - ent - con),
                contradiction_score=con,
            ))
        return out


@pytest.mark.asyncio
async def test_verify_node_passes_with_isolated_contradiction(
    base_state, sample_claims, monkeypatch,
):
    """v10 regression: 1/3 contradiction (33% < 50%) → pass, reject değil.

    Bu test v9'da reject döner (NLI tek-claim veto). v10 ratio-based ile pass
    olmalı çünkü 2/3 desteklenir (66% >= 20% threshold).
    """
    # Claim 0 (TKHK m.11 destekli) → contradiction
    # Claim 1,2 (İK m.32 + TKHK m.999 uydurma) → entailment
    per_claim = _PerClaimFakeVerifier([
        (0.05, 0.85),   # claim 0: NLI veto
        (0.70, 0.05),   # claim 1: entail
        (0.70, 0.05),   # claim 2: entail
    ])
    monkeypatch.setattr(
        "agents.verifier_layers.get_verifier",
        lambda: per_claim,
        raising=False,
    )
    base_state["claims"] = sample_claims  # 3 claims
    result = await verify_node(base_state)
    # 1/3 = 33% < 50% → contradiction reject tetiklenmemeli
    assert result["debate_verdict"] in {"pass", "retry"}
    # Hiç değilse bir tane "1 çelişki" mesajı görmeliyiz
    assert "1 çelişki" in result["debate_notes"]
