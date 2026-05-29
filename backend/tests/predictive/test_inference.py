"""predictive/inference.py — heuristic dava sonucu tahmini (W18).

Emsal kararların sonuç-sinyallerini oylayıp tutucu tahmin üretir; yeterli/uyumlu
sinyal yoksa 'belirsiz'. confidence ASLA 0.85'i geçmez (kesinlik ima etmez).
"""

from __future__ import annotations

import pytest

from predictive.inference import (
    _classify_outcome,
    _heuristic_predict,
    _model_enabled,
    predict_outcome,
)


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


def test_model_disabled_when_no_checkpoint(monkeypatch, tmp_path):
    """Checkpoint dizini yoksa model devre dışı → heuristic yolu kullanılır."""
    monkeypatch.setattr("predictive.inference._MODEL_DIR", str(tmp_path / "yok"))
    monkeypatch.delenv("PREDICTIVE_USE_MODEL", raising=False)
    assert _model_enabled() is False


def test_model_disabled_by_env_toggle(monkeypatch, tmp_path):
    """Dizin VAR olsa bile PREDICTIVE_USE_MODEL=0 → heuristic'e zorla."""
    (tmp_path / "best").mkdir()
    monkeypatch.setattr("predictive.inference._MODEL_DIR", str(tmp_path / "best"))
    monkeypatch.setenv("PREDICTIVE_USE_MODEL", "0")
    assert _model_enabled() is False


@pytest.mark.asyncio
async def test_predict_outcome_falls_back_to_heuristic_without_model(monkeypatch):
    """Model yokken predict_outcome heuristic sonucu döner (BERT yolu atlanır)."""
    monkeypatch.setattr("predictive.inference._MODEL_DIR", "/nonexistent/checkpoint")
    pred = await predict_outcome(
        "soru",
        ["davanın kabulüne karar verildi", "talebin kabulüne karar verildi"],
        ["x", "y"],
    )
    assert pred["verdict_class"] == "kazandi"
    assert "BERT" not in pred["reasoning"]  # heuristic reasoning, model değil


def test_hukum_isolation_ignores_gerekce_section():
    """mle-reviewer kritik bulgusu: gerekçe bölümündeki alt-mahkeme atıfları
    nihai etiketi etkilemez. HÜKÜM bölümündeki nihai karar baskın olur.
    """
    karar_metni = (
        "GEREKÇE: Alt mahkemece davanın reddine karar verilmiş olup, dosya "
        "incelendiğinde delillerin yeterince değerlendirilmediği görülmüştür. "
        "Davacı kıdem tazminatını talep etmiştir. "
        "HÜKÜM: Açıklanan nedenlerle alt mahkeme kararının bozularak "
        "davanın kabulüne, davacı lehine 50.000 TL ödenmesine karar verildi."
    )
    pred = _heuristic_predict([karar_metni] * 3, ["c1", "c2", "c3"])
    # Hüküm bölümünde "kabulüne" → "kazandi" baskın; gerekçedeki "reddine"
    # yok sayılmalı.
    assert pred["verdict_class"] == "kazandi", (
        f"HÜKÜM izolasyonu çalışmadı; çıktı: {pred}"
    )


def test_hukum_isolation_fallback_to_last_800_chars():
    """HÜKÜM başlığı yoksa son 800 karakter izole edilir."""
    text = (
        "Davacı işten çıkarılmış. Davalı işveren itiraz etmiş. "
        "Mahkeme delilleri inceledi. " * 5
        + "Sonuç olarak davanın kabulüne karar verildi."
    )
    pred = _heuristic_predict([text] * 3, ["a", "b", "c"])
    assert pred["verdict_class"] == "kazandi"
