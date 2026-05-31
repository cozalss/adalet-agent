"""eval/quality_gate.py — saf gate mantığı testleri (LLM'siz)."""

from __future__ import annotations

from eval.quality_gate import Scorecard, gate_verdict, score_answers


def _sc(**overrides) -> Scorecard:
    """Geçerli baseline scorecard — testler tek alanı override eder."""
    base = {
        "n": 15, "length_in_target_rate": 0.20, "has_short_answer_rate": 0.83,
        "truncation_rate": 0.0, "avg_src_coverage": 0.70, "unsupported_claim_rate": 0.10,
        "avg_word_count": 80.0, "p95_ms": 15000.0,
    }
    base.update(overrides)
    return Scorecard(**base)


# --- score_answers ---

def test_score_answers_filters_short_circuit():
    rows = [
        {"length_in_target": True, "has_short_answer": True, "is_truncated": False,
         "src_coverage": 0.8, "word_count": 180, "unsupported_claims": 0, "elapsed_ms": 12000},
        {"length_in_target": False, "has_short_answer": False, "is_truncated": False,
         "src_coverage": 0, "word_count": 40, "unsupported_claims": 0, "elapsed_ms": 2},  # kısa-devre
    ]
    sc = score_answers(rows)
    assert sc.n == 1  # kısa-devre elendi
    assert sc.length_in_target_rate == 1.0


def test_score_answers_unsupported_rate():
    rows = [
        {"length_in_target": True, "has_short_answer": True, "is_truncated": False,
         "src_coverage": 0.8, "word_count": 180, "unsupported_claims": 2, "elapsed_ms": 12000},
        {"length_in_target": True, "has_short_answer": True, "is_truncated": False,
         "src_coverage": 0.9, "word_count": 190, "unsupported_claims": 0, "elapsed_ms": 13000},
    ]
    sc = score_answers(rows)
    assert sc.unsupported_claim_rate == 0.5  # 1/2 cevapta kaynaksız iddia var


# --- gate_verdict: hepsi iyileşirse GEÇER ---

def test_gate_passes_when_length_improves_others_stable():
    base = _sc(length_in_target_rate=0.20, avg_word_count=80)
    cand = _sc(length_in_target_rate=0.60, avg_word_count=180)  # hedef-uzunluk arttı
    v = gate_verdict(base, cand)
    assert v["passed"] is True


# --- gate_verdict: her kriter ayrı ayrı FAIL ettirir ---

def test_gate_fails_when_length_drops():
    base = _sc(length_in_target_rate=0.40)
    cand = _sc(length_in_target_rate=0.20)  # hedef-uzunluk DÜŞTÜ
    v = gate_verdict(base, cand)
    assert v["passed"] is False
    assert any("length" in c["name"] and not c["passed"] for c in v["criteria"])


def test_gate_fails_when_truncation_increases():
    base = _sc(truncation_rate=0.0)
    cand = _sc(truncation_rate=0.10)  # cevap kesilme arttı
    v = gate_verdict(base, cand)
    assert v["passed"] is False
    assert any("truncation" in c["name"] and not c["passed"] for c in v["criteria"])


def test_gate_fails_when_src_coverage_drops_beyond_tolerance():
    base = _sc(avg_src_coverage=0.70)
    cand = _sc(avg_src_coverage=0.60)  # 0.10 düşüş > 0.03 tolerans
    v = gate_verdict(base, cand)
    assert v["passed"] is False


def test_gate_allows_src_coverage_drop_within_tolerance():
    base = _sc(avg_src_coverage=0.70, length_in_target_rate=0.20)
    cand = _sc(avg_src_coverage=0.68, length_in_target_rate=0.50)  # 0.02 < 0.03 tolerans
    v = gate_verdict(base, cand)
    assert v["passed"] is True


def test_gate_fails_when_unsupported_increases_beyond_tolerance():
    base = _sc(unsupported_claim_rate=0.10)
    cand = _sc(unsupported_claim_rate=0.20)  # 0.10 artış > 0.02 tolerans
    v = gate_verdict(base, cand)
    assert v["passed"] is False


def test_gate_fails_when_p95_degrades_beyond_factor():
    base = _sc(p95_ms=15000)
    cand = _sc(p95_ms=20000)  # 20000 > 15000*1.20=18000
    v = gate_verdict(base, cand)
    assert v["passed"] is False
    assert any("p95" in c["name"] and not c["passed"] for c in v["criteria"])


def test_gate_allows_p95_within_degrade_factor():
    base = _sc(p95_ms=15000, length_in_target_rate=0.20)
    cand = _sc(p95_ms=17000, length_in_target_rate=0.50)  # 17000 < 18000 tavan
    v = gate_verdict(base, cand)
    assert v["passed"] is True


def test_gate_fails_when_short_answer_drops_beyond_tolerance():
    base = _sc(has_short_answer_rate=0.83)
    cand = _sc(has_short_answer_rate=0.70)  # 0.13 düşüş > 0.05 tolerans
    v = gate_verdict(base, cand)
    assert v["passed"] is False


def test_gate_verdict_includes_full_scorecards():
    v = gate_verdict(_sc(), _sc(length_in_target_rate=0.5))
    assert "baseline" in v and "candidate" in v
    assert v["baseline"]["n"] == 15
    assert len(v["criteria"]) == 6
