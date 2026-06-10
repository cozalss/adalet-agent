"""eval_emsal.case_metrics saf-fonksiyon testleri (P5, 2026-06-10)."""

from __future__ import annotations

from dataclasses import dataclass, field

from scripts.eval_emsal import TOPICAL_THRESHOLD, case_metrics


@dataclass
class _R:
    source: str
    text: str
    score: float
    metadata: dict = field(default_factory=dict)


def _mk(source: str = "yargitay", text: str = "", score: float = 0.5) -> _R:
    return _R(source=source, text=text, score=score)


def test_court_match_uses_expected_sources():
    rs = [_mk("anayasa"), _mk("anayasa"), _mk("anayasa"), _mk("yargitay")]
    m = case_metrics(rs, ["yargitay", "uyap"], [])
    assert m["court@3"] is False  # ilk 3 anayasa
    assert m["court@8"] is True   # 4. sırada yargitay


def test_topical_threshold_stem_aware():
    # 2 keyword'den ikisi de geçiyor → overlap 1.0 ≥ 0.5 → topical
    hit = _mk(text="Davacının kıdem tazminatı talebi ve işçi alacağı incelendi")
    miss = _mk(text="Kamulaştırma bedelinin tespiti istemi")
    m = case_metrics([miss, miss, miss, hit], ["yargitay"], ["kıdem tazminatı", "işçi"])
    assert m["topical@3"] is False
    assert m["topical@8"] is True
    assert m["best_overlap"] >= TOPICAL_THRESHOLD


def test_live_trigger_below_threshold():
    rs = [_mk(score=0.05), _mk(score=0.02)]
    m = case_metrics(rs, ["yargitay"], [])
    assert m["live_trigger"] is True
    assert m["best_score"] == 0.05


def test_empty_results_safe():
    m = case_metrics([], ["yargitay"], ["kira"])
    assert m["n_results"] == 0
    assert m["court@8"] is False and m["topical@8"] is False
    assert m["live_trigger"] is True  # sonuç yok → canlı fallback tetiklenmeli
