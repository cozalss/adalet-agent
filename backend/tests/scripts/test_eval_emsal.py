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
    m = case_metrics([], ["yargitay"], ["kira"], question="kira sorusu")
    assert m["n_results"] == 0
    assert m["court@8"] is False and m["topical@8"] is False
    assert m["live_trigger"] is True  # sonuç yok → canlı fallback tetiklenmeli
    assert m["live_trigger_cov"] is True  # yeni sinyal de boş-sonuçta tetiklenmeli


def test_coverage_trigger_separates_relevant_from_irrelevant():
    """Yeni coverage sinyali: sorgu kelimeleri kararlarda geçiyorsa tetikleme YOK;
    tamamen alakasız kararlarda tetikleme VAR (skor ne olursa olsun)."""
    q = "ev sahibim depozitomu geri vermiyor"
    relevant = _mk(text="Kiracının depozito iadesi talebi: ev sahibi depozitoyu geri vermek zorundadır", score=0.01)
    irrelevant = _mk(text="Kamulaştırma bedelinin artırılması istemiyle açılan davada bilirkişi raporu", score=0.95)
    m_rel = case_metrics([relevant], ["yargitay"], [], question=q)
    m_irr = case_metrics([irrelevant], ["yargitay"], [], question=q)
    assert m_rel["query_coverage"] > m_irr["query_coverage"]
    assert m_rel["live_trigger_cov"] is False   # alakalı → tetikleme yok (skor 0.01 olsa bile!)
    assert m_irr["live_trigger_cov"] is True    # alakasız → tetikle (skor 0.95 olsa bile!)
    # Eski skor sinyalinin tam tersi davrandığını belgele (bulgunun kendisi):
    assert m_rel["live_trigger"] is True and m_irr["live_trigger"] is False


def test_should_trigger_live_modes(monkeypatch):
    """live_emsal.should_trigger_live: coverage default; score modu geri-uyumlu."""
    import importlib

    import agents.config as cfg
    from retrieval.live_emsal import should_trigger_live

    q = "ev sahibim depozitomu geri vermiyor"
    relevant = _mk(text="depozito iadesi: ev sahibi depozitoyu geri vermek zorundadır", score=0.01)

    monkeypatch.setenv("EMSAL_LIVE_TRIGGER_MODE", "coverage")
    importlib.reload(cfg)
    trig, name, _ = should_trigger_live(q, [relevant])
    assert name == "coverage" and trig is False

    monkeypatch.setenv("EMSAL_LIVE_TRIGGER_MODE", "score")
    importlib.reload(cfg)
    trig, name, val = should_trigger_live(q, [relevant])
    assert name == "score" and trig is True and val == 0.01

    monkeypatch.delenv("EMSAL_LIVE_TRIGGER_MODE", raising=False)
    importlib.reload(cfg)  # diğer testler için default'a dön

    assert should_trigger_live(q, [])[0] is True  # boş sonuç her modda tetikler
