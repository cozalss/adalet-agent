"""eval/rerank_cutoff_sweep._summarize — saf agregasyon (LLM/Qdrant'sız, denetim #11)."""

from __future__ import annotations

from eval.rerank_cutoff_sweep import _summarize


def _row(madde_recall=None, n_expected=None, returned=5):
    r = {
        "elapsed_ms": 100.0, "domain@1": True, "domain@5": True, "kanun@5": True,
        "mrr": 1.0, "context_precision@5": 0.8, "got_domains_top5": ["kira"] * returned,
    }
    if n_expected is not None:
        r["n_expected_madde"] = float(n_expected)
        r["madde_recall@5"] = madde_recall
    return r


def test_summarize_empty():
    assert _summarize([]) == {"n": 0}


def test_madde_recall_averaged_over_madde_cases_only():
    rows = [_row(madde_recall=1.0, n_expected=2), _row(madde_recall=0.5, n_expected=1), _row()]
    s = _summarize(rows)
    assert s["n"] == 3
    assert s["n_madde_cases"] == 2           # n_expected_madde'siz vaka hariç
    assert s["madde_recall@5"] == 0.75       # (1.0 + 0.5) / 2


def test_avg_returned_reflects_cutoff_filtering():
    """Cutoff arttıkça dönen-aday sayısı düşer → avg_returned bu precision proxy'sini yakalar."""
    rows = [_row(returned=2), _row(returned=4)]
    assert _summarize(rows)["avg_returned"] == 3.0  # (2 + 4) / 2


def test_no_madde_cases_recall_none():
    assert _summarize([_row(), _row()])["madde_recall@5"] is None
