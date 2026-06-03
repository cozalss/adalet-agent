"""eval/stats.py — Wilson güven aralığı (jüri istatistiksel titizliği)."""

from __future__ import annotations

import pytest

from eval.stats import fmt_ci, wilson_interval


def test_wilson_perfect_small_n_lower_bound_below_one():
    """8/8 → P=1.0 ama %95 alt-sınır <1.0 (küçük-N dürüstlüğü); üst-sınır=1.0."""
    lo, hi = wilson_interval(8, 8)
    assert hi == pytest.approx(1.0, abs=1e-9)
    assert 0.5 < lo < 1.0           # ~0.63 civarı, kesinlikle 1.0 değil


def test_wilson_perfect_large_n_tighter():
    """n büyüdükçe alt-sınır 1.0'a yaklaşır (aralık daralır)."""
    lo_small, _ = wilson_interval(8, 8)
    lo_large, _ = wilson_interval(72, 72)
    assert lo_large > lo_small       # 72/72 alt-sınırı 8/8'den yüksek


def test_wilson_zero_successes_upper_bound():
    """0/32 → alt=0, üst-sınır küçük ama >0 ('oran üst-sınırla X altında')."""
    lo, hi = wilson_interval(0, 32)
    assert lo == 0.0
    assert 0.0 < hi < 0.2            # ~0.106


def test_wilson_clamped_to_unit_interval():
    for k, n in [(1, 1), (0, 1), (5, 10), (99, 100)]:
        lo, hi = wilson_interval(k, n)
        assert 0.0 <= lo <= hi <= 1.0


def test_wilson_n_zero_returns_full_interval():
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_half_is_symmetric_around_half():
    lo, hi = wilson_interval(50, 100)
    assert lo + hi == pytest.approx(1.0, abs=1e-9)  # p=0.5 → simetrik


def test_fmt_ci_string_shape():
    s = fmt_ci(7, 8)
    assert s.startswith("[") and s.endswith("]") and "," in s
