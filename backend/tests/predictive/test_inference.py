"""predictive/inference.py — heuristic dava sonucu tahmini (W18).

Emsal kararların sonuç-sinyallerini oylayıp tutucu tahmin üretir; yeterli/uyumlu
sinyal yoksa 'belirsiz'. confidence ASLA 0.85'i geçmez (kesinlik ima etmez).
"""

from __future__ import annotations

import pytest

from predictive.inference import _classify_outcome, _heuristic_predict, predict_outcome


def test_classify_kazandi():
    assert _classify_outcome("davanın kabulüne karar verilmiştir") == "kazandi"


def test_classify_kaybetti():
    assert _classify_outcome("davanın reddine karar verilmiştir") == "kaybetti"


def test_classify_kismi_explicit():
    assert _classify_outcome("davanın kısmen kabulüne karar verildi") == "kismi"


def test_classify_kismi_on_mixed_signal():
    """Hem kabul hem ret standalone → çelişen sinyal = kismi."""
    txt = "talebin kabulüne, fazlaya ilişkin istemin reddine karar verildi"
    assert _classify_outcome(txt) == "kismi"


def test_classify_none_when_no_signal():
    assert _classify_outcome("bu metinde net bir sonuç bilgisi yoktur") is None


def test_heuristic_majority_kazandi():
    texts = [
        "davanın kabulüne karar verildi",
        "talebin kabulüne karar verildi",
        "davanın reddine karar verildi",
    ]
    ids = ["c1", "c2", "c3"]
    pred = _heuristic_predict(texts, ids)
    assert pred["verdict_class"] == "kazandi"
    assert 0.0 < pred["confidence"] <= 0.85
    assert pred["similar_case_ids"] == ids


def test_heuristic_confidence_capped():
    """Tam uyumlu çok emsalde bile confidence ≤ 0.85."""
    texts = ["davanın kabulüne karar verildi"] * 8
    pred = _heuristic_predict(texts, [f"c{i}" for i in range(8)])
    assert pred["verdict_class"] == "kazandi"
    assert pred["confidence"] <= 0.85


def test_heuristic_belirsiz_when_insufficient_signal():
    """Sinyal < 2 → belirsiz (uydurma kazanma oranı yok)."""
    texts = ["davanın kabulüne karar verildi", "sonuç içermeyen metin"]
    pred = _heuristic_predict(texts, ["c1", "c2"])
    assert pred["verdict_class"] == "belirsiz"
    assert pred["confidence"] <= 0.3
    assert "avukat" in pred["reasoning"].lower()


def test_heuristic_belirsiz_empty():
    pred = _heuristic_predict([], [])
    assert pred["verdict_class"] == "belirsiz"
    assert pred["confidence"] == 0.0


@pytest.mark.asyncio
async def test_predict_outcome_async_interface():
    texts = [
        "davanın reddine karar verildi",
        "talebin reddine karar verildi",
        "davanın kabulüne karar verildi",
    ]
    pred = await predict_outcome("İşten çıkarıldım, tazminat alır mıyım?", texts, ["a", "b", "c"])
    assert pred["verdict_class"] == "kaybetti"
    assert pred["similar_case_ids"] == ["a", "b", "c"]
    assert isinstance(pred["reasoning"], str) and pred["reasoning"]
