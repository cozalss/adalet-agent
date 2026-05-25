"""LLMJudge + sampling testleri.

MockLLM judge formatını tanır (llm.py _mock_json_response). Bu yüzden gerçek
evaluate çağrısı MockLLM çıktısıyla deterministic çalışır.
"""

from __future__ import annotations

import pytest

from eval.judge import JudgeScore, LLMJudge, _clamp01, _parse_judge_json, should_sample


def test_should_sample_zero_rate_never():
    assert should_sample("any-id", rate=0.0) is False


def test_should_sample_full_rate_always():
    assert should_sample("any-id", rate=1.0) is True


def test_should_sample_deterministic_for_same_id():
    """Aynı call_id her zaman aynı sonucu vermeli."""
    a = should_sample("call-123", rate=0.5)
    b = should_sample("call-123", rate=0.5)
    assert a == b


def test_should_sample_distribution_around_target():
    """1000 vakada %20 rate yaklaşık %15-25 arası örneklem."""
    sampled = sum(1 for i in range(1000) if should_sample(f"call-{i}", rate=0.20))
    # Geniş bant — deterministic hash ama uniform olmayabilir
    assert 100 <= sampled <= 350


def test_clamp01_normal():
    assert _clamp01(0.5) == 0.5
    assert _clamp01(0.0) == 0.0
    assert _clamp01(1.0) == 1.0


def test_clamp01_out_of_range():
    assert _clamp01(1.5) == 1.0
    assert _clamp01(-0.3) == 0.0


def test_clamp01_invalid_input():
    assert _clamp01("not a number") == 0.0
    assert _clamp01(None) == 0.0


def test_parse_judge_json_strips_fence():
    raw = '```json\n{"faithful": 0.9, "complete": 0.8, "tone": 0.7, "notes": "ok"}\n```'
    s = _parse_judge_json(raw)
    assert s.faithful == 0.9
    assert s.complete == 0.8
    assert s.tone == 0.7
    assert s.notes == "ok"


def test_parse_judge_json_bad_returns_zero():
    s = _parse_judge_json("not json {{{")
    assert s.faithful == 0.0
    assert s.complete == 0.0


def test_judge_score_overall():
    s = JudgeScore(faithful=1.0, complete=0.5, tone=0.5, notes="ok")
    # 0.5*1 + 0.3*0.5 + 0.2*0.5 = 0.5 + 0.15 + 0.10 = 0.75
    assert s.overall() == 0.75


def test_judge_score_dict_roundtrip():
    s = JudgeScore(faithful=0.9, complete=0.7, tone=0.8, notes="iyi")
    d = s.to_dict()
    assert d["faithful"] == 0.9
    assert d["overall"] == s.overall()


@pytest.mark.asyncio
async def test_judge_evaluate_mocked_returns_score():
    """MockLLM judge JSON formatını tanır → makul skorlar döner."""
    judge = LLMJudge()
    s = await judge.evaluate(
        question="Kıdem tazminatı nedir?",
        context_snippets=["İş kanunu m.32: işveren ücret ödemeli."],
        answer="Kıdem tazminatı işten ayrılma tazminatıdır.",
    )
    # MockLLM JSON: faithful=0.85, complete=0.75, tone=0.80
    assert 0.7 <= s.faithful <= 1.0
    assert s.overall() > 0.5


@pytest.mark.asyncio
async def test_judge_evaluate_empty_inputs():
    judge = LLMJudge()
    s = await judge.evaluate("", [], "")
    assert s.faithful == 0.0
    assert "boş" in s.notes.lower()


# --------------------------------------------------------------------------
#  Sprint-4 W2.6: determinism — temperature=0.0 + JSON-mode + tam kapsam
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_deterministic_repeat():
    """Aynı (soru/cevap/kaynak) tekrar çağrıda aynı skor döner."""
    judge = LLMJudge()
    question = "Kira artış oranı nasıl belirlenir?"
    ctx = ["TBK m.344: kira bedeli yıllık TÜFE artışını aşamaz."]
    answer = "Kira artışı yıllık TÜFE oranını geçemez."

    s1 = await judge.evaluate(question, ctx, answer)
    s2 = await judge.evaluate(question, ctx, answer)
    s3 = await judge.evaluate(question, ctx, answer)

    # MockLLM temperature=0.0 + sabit prompt → identical output beklenir
    assert s1.faithful == s2.faithful == s3.faithful
    assert s1.complete == s2.complete == s3.complete
    assert s1.tone == s2.tone == s3.tone
    assert s1.overall() == s2.overall() == s3.overall()


def test_judge_sample_rate_default_is_full():
    """Sprint-4 W2.6: JUDGE_SAMPLE_RATE default 1.0 (tam örneklem).

    Module-level default'u env'den okur — env'de override yoksa 1.0 olmalı.
    Bu test gerçek env'i kontrol eder; CI/conftest override etmediği için
    default değer geçerli kalır.
    """
    import os as _os

    import eval.judge as judge_mod

    # Conftest JUDGE_SAMPLE_RATE set ediyor mu? Etmiyor — default 1.0 olmalı.
    env_rate = _os.environ.get("JUDGE_SAMPLE_RATE")
    if env_rate is None:
        assert judge_mod.JUDGE_SAMPLE_RATE == 1.0
    else:
        # Env override edilmişse skip — değer env'le tutarlı olmalı
        assert float(env_rate) == judge_mod.JUDGE_SAMPLE_RATE
