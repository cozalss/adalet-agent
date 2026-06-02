"""predictive/inference.py BERT yolu — _facts_before_hukum + _model_predict (mock model).

Eski test'ler yalnız model-KAPALI (heuristic) yolu kapsıyordu; bu dosya model-AÇIK
yolu fake model ile sınar (train/serve hizalama fix'i: BERT artık emsal-facts kullanır).
"""

from __future__ import annotations

import numpy as np

from predictive import inference as inf

# --- _facts_before_hukum (hüküm-öncesi olay+gerekçe, sızıntısız) ---


def test_facts_before_hukum_strips_hukum():
    text = "Olay: davacı işten çıkarıldı. Gerekçe: haklı sebep yok. HÜKÜM: davanın kabulüne"
    facts = inf._facts_before_hukum(text)
    assert "kabul" not in facts.lower()  # hüküm dışlandı (sızıntı yok)
    assert "Olay" in facts and "Gerekçe" in facts


def test_facts_before_hukum_sonuc_header():
    text = "Dava konusu kira alacağı. SONUÇ: reddine karar verildi"
    facts = inf._facts_before_hukum(text)
    assert "reddine" not in facts.lower()
    assert "kira alacağı" in facts


def test_facts_before_hukum_no_header_returns_all():
    text = "Başlıksız kısa karar metni gövdesi burada."
    assert inf._facts_before_hukum(text) == text


# --- _model_predict (fake model ile BERT yolu) ---


class _FakeEnc(dict):
    def to(self, _device):
        return self


class _FakeTok:
    def __call__(self, inputs, **_kw):
        e = _FakeEnc()
        e["_n"] = len(inputs) if isinstance(inputs, list) else 1
        return e


class _FakeLogits:
    def __init__(self, arr):
        self._arr = arr

    def cpu(self):
        return self

    def numpy(self):
        return self._arr


class _FakeOut:
    def __init__(self, arr):
        self.logits = _FakeLogits(arr)


class _FakeModel:
    """Her input için sabit logit döndürür (n×3)."""

    def __init__(self, per_input_logits):
        self._l = per_input_logits

    def __call__(self, **enc):
        n = enc.get("_n", 1)
        return _FakeOut(np.array([self._l] * n, dtype=np.float64))


def _patch_model(monkeypatch, logits):
    monkeypatch.setattr(inf, "_load_model", lambda _d: (_FakeTok(), _FakeModel(logits), 1.0))


def test_model_predict_kazandi_from_emsal_facts(monkeypatch):
    _patch_model(monkeypatch, [4.0, 0.0, 0.0])  # kazandi=0 baskın
    # ≥_MIN_SIGNAL (2) yeterli-uzunlukta emsal-facts → gerçek tahmin (guard'ı geçer).
    emsal = [
        "Olay: davacı kıdem tazminatı istedi, bir yıl çalıştı ve hak doğdu gerekçesi. HÜKÜM: kabul",
        "Olay: başka davacı kıdem için başvurdu, yeterince uzun gerekçe metni mevcut. HÜKÜM: kabul",
    ]
    pred = inf._model_predict("kıdem alır mıyım", emsal, ["c1", "c2"])
    assert pred["verdict_class"] == "kazandi"
    assert pred["confidence"] <= 0.85  # tavan korunur
    assert "emsal" in pred["reasoning"].lower()  # emsal-facts kaynaklı


def test_model_predict_averages_over_emsal(monkeypatch):
    # 2 emsal, model her birine aynı logit → kaybetti baskın
    _patch_model(monkeypatch, [0.0, 4.0, 0.0])
    emsal = [
        "Olay A uzun gerekçe metni burada yeterince uzun olacak şekilde yazıldı. HÜKÜM: ret",
        "Olay B yine yeterince uzun bir gerekçe metni içeriyor ki facts kullanılsın. HÜKÜM: ret",
    ]
    pred = inf._model_predict("soru", emsal, ["a", "b"])
    assert pred["verdict_class"] == "kaybetti"
    assert "2 emsal" in pred["reasoning"]


def test_model_predict_belirsiz_without_enough_facts(monkeypatch):
    _patch_model(monkeypatch, [0.0, 0.0, 4.0])  # logit önemsiz — guard önce devreye girer
    # Yetersiz emsal-facts (tek karar + hüküm-öncesi <40 char) → kendinden emin BERT
    # tahmini YERİNE düşük-güven "belirsiz" (vatandaşı yanıltma; question-fallback YOK).
    pred = inf._model_predict("Kısa soru", ["HÜKÜM: kabul"], ["c1"])
    assert pred["verdict_class"] == "belirsiz"
    assert pred["confidence"] <= 0.25  # yetersiz emsal → düşük güven
    assert "yetersiz" in pred["reasoning"].lower()
