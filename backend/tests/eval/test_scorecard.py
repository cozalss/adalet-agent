"""eval/scorecard.py — deterministik yarışma karnesi testleri (LLM'siz, anında)."""

from __future__ import annotations

from eval.scorecard import build_scorecard, render_console, render_markdown


def test_scorecard_reflects_live_shield_metrics():
    """Karne canlı gold-set'leri yansıtır: kalkan kusursuz (yanlış-veto=0, tam yakalama)."""
    sc = build_scorecard()
    hs = sc["hallucination_shield"]
    assert hs["n"] >= 100                          # adversarial ölçek
    assert hs["false_veto_count"] == 0             # iyi cevabı asla reddetme (kritik)
    assert hs["hallucination_recall"] == 1.0
    assert hs["micro_precision"] == 1.0
    assert sc["fabricated_threshold"]["precision"] == 1.0
    assert sc["shield_pass"] is True


def test_scorecard_coverage_lists_known_sets():
    """Veri-kapsam bölümü bilinen setleri sayar (jüri breadth kanıtı)."""
    cov = {c["set"]: c["n"] for c in build_scorecard()["dataset_coverage"]}
    assert cov["hallucination_gold.jsonl"] >= 100
    assert cov["eligibility_adversarial.jsonl"] >= 16


def test_render_markdown_is_jury_ready():
    """Markdown rapor başlık metriklerini ve kritik garanti satırını içerir."""
    md = render_markdown(build_scorecard())
    assert "Sıfır-Halüsinasyon" in md
    assert "Yanlış-veto" in md
    assert "FABRİKE-eşik" in md
    assert "| Detektör türü |" in md  # tablo başlığı


def test_render_console_shows_verdict():
    out = render_console(build_scorecard())
    assert "KARNESİ" in out
    assert "GEÇTİ" in out  # kalkan pass → GEÇTİ
