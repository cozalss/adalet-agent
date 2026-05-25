"""Ragas-uyumlu lokal evaluator — MockLLM tabanlı testler."""

from __future__ import annotations

import math

import pytest

from eval.ragas_full import (
    EvalSample,
    RagasEvaluator,
    _fallback_split,
    _mean_nan,
    _round_or_none,
    _safe_json,
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)


@pytest.mark.asyncio
async def test_faithfulness_with_mock_returns_in_range():
    """MockLLM entail=yes → 1.0 oranı bekleriz."""
    ans = "Tüketici Madde 11'e göre iade isteyebilir. Süre 30 gündür."
    ctx = ["Madde 11: Tüketici 30 gün içinde ayıplı malı iade edebilir."]
    score = await faithfulness(ans, ctx)
    assert 0.0 <= score <= 1.0
    # MockLLM "yes" döner → 1.0 beklenir
    assert score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_faithfulness_empty_answer_returns_nan():
    s = await faithfulness("", ["ctx"])
    assert math.isnan(s)


@pytest.mark.asyncio
async def test_faithfulness_no_context_returns_nan():
    s = await faithfulness("answer", [])
    assert math.isnan(s)


@pytest.mark.asyncio
async def test_answer_relevancy_returns_score_or_nan(monkeypatch):
    """BGE-M3 yüklenemezse fallback (W2.5: 0.5), yüklenirse [0,1] aralık.

    Sprint-4 W2.5 not: format() bug fix sonrası bu test gerçekten LLM'i
    çağırıyor; Windows + torch.cpu Embedder gerçek yüklemesini engellemek
    için `_cosine_similarity_batch` mock'lanıyor — test deterministic.
    """
    import eval.ragas_full as ragas_mod

    def _mock_cosine(reference, candidates):
        # Fake similarity: tüm candidate'lar referansa eşit yakın
        return [0.8] * len(candidates), True

    monkeypatch.setattr(ragas_mod, "_cosine_similarity_batch", _mock_cosine)

    score = await answer_relevancy(
        question="Tüketici hakları nedir?",
        answer="Tüketici 30 gün içinde iade hakkına sahiptir.",
    )
    # NaN ASLA dönmemeli (W2.5 spec); embed fail olsa bile fallback skoru
    assert not math.isnan(score)
    assert 0.0 <= score <= 1.0


@pytest.mark.asyncio
async def test_answer_relevancy_fallback_when_embedder_unavailable(monkeypatch):
    """Sprint-4 W2.5: Embedder ImportError → fallback skor (0.5)."""
    import eval.ragas_full as ragas_mod

    def _broken_cosine(reference, candidates):
        return [], False   # embed_ok=False

    monkeypatch.setattr(ragas_mod, "_cosine_similarity_batch", _broken_cosine)
    score = await answer_relevancy(
        question="soru?",
        answer="cevap.",
    )
    assert score == pytest.approx(ragas_mod.RAGAS_RELEVANCY_FALLBACK_SCORE)


@pytest.mark.asyncio
async def test_answer_relevancy_fallback_on_empty_sims(monkeypatch):
    """Sprint-4 W2.5: embed OK ama math edge (sims=[]) → fallback skor."""
    import eval.ragas_full as ragas_mod

    def _empty_sims(reference, candidates):
        return [], True   # embed_ok=True ama sims empty

    monkeypatch.setattr(ragas_mod, "_cosine_similarity_batch", _empty_sims)
    score = await answer_relevancy(
        question="soru?",
        answer="cevap.",
    )
    assert score == pytest.approx(ragas_mod.RAGAS_RELEVANCY_FALLBACK_SCORE)


@pytest.mark.asyncio
async def test_context_precision_mock_yields_one():
    """MockLLM useful=yes → 1.0 oranı."""
    score = await context_precision(
        question="Tüketici hakkı?",
        answer="Madde 11 iade hakkı verir.",
        contexts=["Madde 11 ayıplı malda iade hakkı verir."],
    )
    # MockLLM her zaman yes → 1.0
    assert score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_context_recall_with_ground_truth():
    score = await context_recall(
        ground_truth="Tüketici 30 gün içinde iade hakkına sahiptir.",
        contexts=["Madde 11: 30 günlük iade süresi."],
    )
    assert 0.0 <= score <= 1.0


@pytest.mark.asyncio
async def test_context_recall_empty_gt_returns_nan():
    s = await context_recall("", ["ctx"])
    assert math.isnan(s)


@pytest.mark.asyncio
async def test_evaluator_batch_aggregates():
    samples = [
        EvalSample(
            question="Tüketici hakkı?",
            answer="Madde 11 iade hakkı verir.",
            contexts=["Madde 11 iade hakkı tanır."],
            ground_truth="Tüketici iade isteyebilir.",
        ),
        EvalSample(
            question="Kıdem tazminatı?",
            answer="İş Kanunu Madde 32 ücret ödeme zorunlulu kurar.",
            contexts=["Madde 32 ücreti düzenler."],
            ground_truth=None,
        ),
    ]
    out = await RagasEvaluator().evaluate_batch(samples)
    assert out["n_samples"] == 2
    assert "faithfulness" in out
    assert "per_sample" in out
    assert len(out["per_sample"]) == 2


@pytest.mark.asyncio
async def test_evaluator_empty_batch():
    out = await RagasEvaluator().evaluate_batch([])
    assert out["n_samples"] == 0
    assert math.isnan(out["faithfulness"])


def test_safe_json_handles_fence():
    obj = _safe_json('```json\n{"a": 1}\n```')
    assert obj == {"a": 1}


def test_safe_json_handles_garbage():
    assert _safe_json("not json") == {}


def test_fallback_split_filters_short_sentences():
    text = "Kısa. Bu daha uzun ve anlamlı bir cümledir. Diğer bir uzun cümle."
    sents = _fallback_split(text)
    # "Kısa." 5 char ama strip sonrası len > 20 değil → atlamalı
    assert all(len(s) > 20 for s in sents)


def test_mean_nan_skips_nan():
    assert _mean_nan([1.0, 2.0, math.nan]) == 1.5
    assert math.isnan(_mean_nan([math.nan, math.nan]))


def test_round_or_none():
    assert _round_or_none(math.nan) is None
    assert _round_or_none(0.123456) == 0.1235
