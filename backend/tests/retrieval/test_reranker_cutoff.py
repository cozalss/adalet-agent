"""retrieval/reranker.py — RERANK_SCORE_MIN alaka eşiği (W23).

Cross-encoder skoru eşik altındaki adaylar elenmeli; default 0.0 = kapalı
(baseline). Gerçek model yüklenmez — _model fake ile enjekte edilir.
"""

from __future__ import annotations

from retrieval import reranker as rr_mod
from retrieval.reranker import Reranker


class _FakeScores:
    def __init__(self, scores: list[float]) -> None:
        self._scores = scores

    def tolist(self) -> list[float]:
        return self._scores


class _FakeModel:
    def __init__(self, scores: list[float]) -> None:
        self._scores = scores

    def predict(self, _pairs, convert_to_numpy=True):
        return _FakeScores(self._scores)


def _reranker_with_scores(scores: list[float]) -> Reranker:
    r = Reranker()
    # cached_property bypass — gerçek CrossEncoder yüklenmesin.
    r.__dict__["_model"] = _FakeModel(scores)
    return r


_CANDS = [
    {"text": "alakalı emsal", "chunk_id": "c1", "score": 0.5},
    {"text": "yarı alakalı", "chunk_id": "c2", "score": 0.5},
    {"text": "alakasız metin", "chunk_id": "c3", "score": 0.5},
]


def test_no_cutoff_returns_all_sorted(monkeypatch):
    monkeypatch.setattr(rr_mod, "RERANK_SCORE_MIN", 0.0)
    r = _reranker_with_scores([0.9, 0.2, 0.05])
    out = r.rerank("soru", _CANDS, top_k=5)
    assert len(out) == 3
    # skora göre azalan sıralı
    assert out[0].chunk_id == "c1"
    assert [round(x.score, 2) for x in out] == [0.9, 0.2, 0.05]


def test_cutoff_drops_low_scores(monkeypatch):
    monkeypatch.setattr(rr_mod, "RERANK_SCORE_MIN", 0.3)
    r = _reranker_with_scores([0.9, 0.2, 0.05])
    out = r.rerank("soru", _CANDS, top_k=5)
    # yalnız 0.9 eşiği geçer
    assert len(out) == 1
    assert out[0].chunk_id == "c1"


def test_cutoff_all_dropped_returns_empty(monkeypatch):
    """Hepsi eşik altıysa boş → çağıran 'kaynak yok' yoluna gider."""
    monkeypatch.setattr(rr_mod, "RERANK_SCORE_MIN", 0.5)
    r = _reranker_with_scores([0.1, 0.2, 0.05])
    out = r.rerank("soru", _CANDS, top_k=5)
    assert out == []


def test_empty_candidates():
    r = _reranker_with_scores([])
    assert r.rerank("soru", [], top_k=5) == []
