"""verify_node fail-closed (VERIFY_STRICT) testleri.

CLAUDE.md §1 — SIFIR HALÜSİNASYON: bir doğrulayıcı (NLI / LettuceDetect)
*yüklü olması beklenirken* çökerse, iddiayı sessizce "doğrulanmamış ama geçer"
saymak halüsinasyon riskini gizler. Strict modda (VERIFY_STRICT=1) bu durum
fail-closed reject üretmeli.

Default (VERIFY_STRICT=0, dev/test/mock) davranış graceful degrade'dir; o yol
`test_verify_node.py::test_verify_node_skips_nli_gracefully_when_unavailable`
ile korunur. Buradaki son test de aynı geri-uyumu bu dosyada bir kez daha
doğrular (regression guard).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agents.config import is_verify_strict
from agents.nodes.verify import verify_node

# --------------------------------------------------------------------------
#  Yardımcı fake'ler
# --------------------------------------------------------------------------


@dataclass
class _FakeLettuceResult:
    grounding_score: float
    fallback_used: bool


class _OkLettuce:
    """Sorunsuz çalışan LettuceDetect mock — NLI yolunu izole etmek için."""

    async def grounding_score(self, _claim: str, _evidences: list[str]):
        return _FakeLettuceResult(grounding_score=0.9, fallback_used=False)


class _BoomLettuce:
    """grounding_score her çağrıda patlar (inference çöküşü senaryosu)."""

    async def grounding_score(self, _claim: str, _evidences: list[str]):
        raise RuntimeError("lettuce inference çöktü")


def _nli_boom():
    raise RuntimeError("transformers/torch yok")


# --------------------------------------------------------------------------
#  is_verify_strict env okuması
# --------------------------------------------------------------------------


def test_is_verify_strict_default_false(monkeypatch):
    monkeypatch.delenv("VERIFY_STRICT", raising=False)
    assert is_verify_strict() is False


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes"])
def test_is_verify_strict_truthy(monkeypatch, val):
    monkeypatch.setenv("VERIFY_STRICT", val)
    assert is_verify_strict() is True


# --------------------------------------------------------------------------
#  Strict mode → fail-closed reject
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_nli_failure_rejects(base_state, sample_claims, monkeypatch):
    """Strict + NLI çökerse → reject, tüm claim'ler unverified."""
    monkeypatch.setenv("VERIFY_STRICT", "1")
    # Lettuce sorunsuz çalışsın ki NLI yolunu izole edelim.
    monkeypatch.setattr("agents.verifier_layers.get_lettuce", _OkLettuce, raising=False)
    monkeypatch.setattr("agents.verifier_layers.get_verifier", _nli_boom, raising=False)

    base_state["claims"] = sample_claims[:2]
    result = await verify_node(base_state)

    assert result["debate_verdict"] == "reject"
    assert len(result["verified_claims"]) == 2
    assert all(not c["verified"] for c in result["verified_claims"])
    assert "kullanılamadı" in result["debate_notes"].lower()


@pytest.mark.asyncio
async def test_strict_lettuce_factory_failure_rejects(
    base_state, sample_claims, monkeypatch,
):
    """Strict + LettuceDetect yüklenemezse → reject."""
    monkeypatch.setenv("VERIFY_STRICT", "1")

    def _lettuce_boom():
        raise RuntimeError("lettuce modeli yok")

    monkeypatch.setattr(
        "agents.verifier_layers.get_lettuce", _lettuce_boom, raising=False,
    )

    base_state["claims"] = sample_claims[:2]
    result = await verify_node(base_state)

    assert result["debate_verdict"] == "reject"
    assert all(not c["verified"] for c in result["verified_claims"])


@pytest.mark.asyncio
async def test_strict_lettuce_inference_failure_rejects(
    base_state, sample_claims, monkeypatch,
):
    """Strict + LettuceDetect inference çağrısı patlarsa → reject."""
    monkeypatch.setenv("VERIFY_STRICT", "1")
    monkeypatch.setattr(
        "agents.verifier_layers.get_lettuce", _BoomLettuce, raising=False,
    )

    base_state["claims"] = sample_claims[:2]
    result = await verify_node(base_state)

    assert result["debate_verdict"] == "reject"


# --------------------------------------------------------------------------
#  Non-strict (default) → graceful degrade (geri-uyum regression guard)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_strict_nli_failure_degrades(
    base_state, sample_claims, monkeypatch,
):
    """VERIFY_STRICT yokken NLI çökse bile reject'e ZORLAMAZ — fuzzy çalışır."""
    monkeypatch.delenv("VERIFY_STRICT", raising=False)
    monkeypatch.setattr("agents.verifier_layers.get_lettuce", _OkLettuce, raising=False)
    monkeypatch.setattr("agents.verifier_layers.get_verifier", _nli_boom, raising=False)

    base_state["claims"] = sample_claims[:2]
    result = await verify_node(base_state)

    # Fail-closed tetiklenmemeli: verdict reject'e zorlanmadı, claim'ler işlendi.
    assert len(result["verified_claims"]) == 2
    assert "kullanılamadı" not in result["debate_notes"].lower()


# --------------------------------------------------------------------------
#  VERIFY_ENABLED=0 ablation bypass (paper §4.2 OFF-arm)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_enabled_zero_bypasses_all_checks(
    base_state, sample_claims, monkeypatch,
):
    """VERIFY_ENABLED=0 → doğrulama TAMAMEN bypass; tüm claim'ler supported, pass.

    Ablation OFF-arm: ham RAG-LLM gibi davranmalı (hiçbir katman koşmaz).
    Doğrulayıcıları bilerek patlat — bypass onlara hiç dokunmamalı (çağırsaydı
    fixture-less ortamda farklı sonuç çıkardı). Bu, §4.2'nin "verify kapalıyken
    uydurma iddialar geçer" ölçümünün temelini garanti eder.
    """
    monkeypatch.setenv("VERIFY_ENABLED", "0")
    monkeypatch.delenv("VERIFY_STRICT", raising=False)
    monkeypatch.setattr("agents.verifier_layers.get_lettuce", _BoomLettuce, raising=False)
    monkeypatch.setattr("agents.verifier_layers.get_verifier", _nli_boom, raising=False)

    base_state["claims"] = sample_claims[:3]
    result = await verify_node(base_state)

    assert result["debate_verdict"] == "pass"
    assert len(result["verified_claims"]) == 3
    assert all(c["verified"] for c in result["verified_claims"])
    assert "bypass" in result["debate_notes"].lower()


@pytest.mark.asyncio
async def test_verify_enabled_default_does_not_bypass(
    base_state, sample_claims, monkeypatch,
):
    """VERIFY_ENABLED set DEĞİLse (default ON) bypass tetiklenmez — normal yol koşar."""
    monkeypatch.delenv("VERIFY_ENABLED", raising=False)
    monkeypatch.delenv("VERIFY_STRICT", raising=False)
    monkeypatch.setattr("agents.verifier_layers.get_lettuce", _OkLettuce, raising=False)
    monkeypatch.setattr("agents.verifier_layers.get_verifier", _nli_boom, raising=False)

    base_state["claims"] = sample_claims[:2]
    result = await verify_node(base_state)

    # Bypass notu OLMAMALI — normal aggregation çalıştı.
    assert "bypass" not in result["debate_notes"].lower()
