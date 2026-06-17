from __future__ import annotations

from eval.typo_robustness import build_typo_cases, mutate_question


def test_mutate_question_diacritic_preserves_numbers():
    out = mutate_question("TBK m. 344 kira artışı TÜFE sınırı", "diacritic")
    assert "344" in out
    assert "artisi" in out
    assert "TUFE" in out


def test_mutate_question_single_edit_keeps_law_refs():
    out = mutate_question("İK m. 17 ihbar tazminatı süreleri", "single_edit")
    assert "17" in out
    assert "İK" in out
    assert out != "İK m. 17 ihbar tazminatı süreleri"


def test_build_typo_cases_carries_gold_fields():
    rows = [{
        "id": "case-1",
        "soru": "kıdem tazminatı nasıl hesaplanır",
        "expected_domain": "isHukuku",
        "expected_madde_no": [14],
    }]
    out = build_typo_cases(rows, levels=("diacritic", "boundary"))

    assert len(out) == 2
    assert all(item["clean_soru"] == rows[0]["soru"] for item in out)
    assert all(item["expected_domain"] == "isHukuku" for item in out)
    assert {item["typo_level"] for item in out} == {"diacritic", "boundary"}
