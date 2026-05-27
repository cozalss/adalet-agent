"""eval/verify_calibration.py — deterministik kalibrasyon harness testleri.

Model GEREKMEZ: layer1 (rules) + layer2 (fuzzy) + layer2.5 (lettuce fallback)
hepsi saf-Python/rapidfuzz. NLI yolu burada test edilmez (opsiyonel).
"""

from __future__ import annotations

import pytest

from eval.verify_calibration import (
    CaseScore,
    Confusion,
    GoldCase,
    build_nli_section,
    build_report,
    confusion,
    contradiction_detected,
    load_gold,
    score_case,
    separation,
    support_full,
    support_modelfree,
    support_with_lettuce,
    sweep,
    verdict_table,
)


def _cs(
    cid: str, should: bool, l1: bool, fuzzy: float, lettuce: float,
    cat: str = "x",
) -> CaseScore:
    return CaseScore(
        id=cid, category=cat, should_support=should,
        l1_ok=l1, fuzzy=fuzzy, lettuce=lettuce,
    )


# --------------------------------------------------------------------------
#  Confusion matrix matematiği
# --------------------------------------------------------------------------

def test_confusion_counts():
    # 2 doğru-pozitif, 1 yanlış-pozitif, 1 doğru-negatif, 1 yanlış-negatif
    decisions = [True, True, True, False, False]
    golds = [True, True, False, False, True]
    cm = confusion(decisions, golds)
    assert (cm.tp, cm.fp, cm.tn, cm.fn) == (2, 1, 1, 1)


def test_confusion_precision_recall_f1():
    cm = Confusion(tp=3, fp=1, tn=4, fn=2)
    assert cm.precision == pytest.approx(3 / 4)
    assert cm.recall == pytest.approx(3 / 5)
    assert cm.accuracy == pytest.approx(7 / 10)
    expected_f1 = 2 * (3 / 4) * (3 / 5) / (3 / 4 + 3 / 5)
    assert cm.f1 == pytest.approx(expected_f1)


def test_confusion_empty_no_division_error():
    cm = Confusion(tp=0, fp=0, tn=0, fn=0)
    assert cm.precision == 0.0
    assert cm.recall == 0.0
    assert cm.f1 == 0.0
    assert cm.accuracy == 0.0


def test_confusion_length_mismatch_raises():
    with pytest.raises(ValueError):
        confusion([True], [True, False])


# --------------------------------------------------------------------------
#  Karar fonksiyonları (production mantığı)
# --------------------------------------------------------------------------

def test_support_modelfree_requires_l1_and_fuzzy():
    # fuzzy yeterli ama format başarısız → desteklenmez
    assert support_modelfree(_cs("a", True, l1=False, fuzzy=0.9, lettuce=0.9), 0.55) is False
    # format ok + fuzzy eşik üstü → destek
    assert support_modelfree(_cs("b", True, l1=True, fuzzy=0.60, lettuce=0.0), 0.55) is True
    # format ok + fuzzy eşik altı → destek yok
    assert support_modelfree(_cs("c", True, l1=True, fuzzy=0.40, lettuce=0.9), 0.55) is False


def test_support_with_lettuce_or_logic():
    # fuzzy düşük ama lettuce yüksek → destek (hipotetik yol)
    cs = _cs("a", True, l1=True, fuzzy=0.30, lettuce=0.70)
    assert support_with_lettuce(cs, fuzzy_th=0.55, lettuce_th=0.50) is True
    # ikisi de düşük → destek yok
    cs2 = _cs("b", True, l1=True, fuzzy=0.30, lettuce=0.30)
    assert support_with_lettuce(cs2, fuzzy_th=0.55, lettuce_th=0.50) is False
    # format başarısız → her zaman False
    cs3 = _cs("c", True, l1=False, fuzzy=0.99, lettuce=0.99)
    assert support_with_lettuce(cs3, fuzzy_th=0.55, lettuce_th=0.50) is False


def test_sweep_monotone_recall_decreases_as_threshold_rises():
    scores = [
        _cs("p1", True, True, 0.50, 0.0),
        _cs("p2", True, True, 0.65, 0.0),
        _cs("n1", False, True, 0.45, 0.0),
    ]
    res = sweep(scores, [0.40, 0.55, 0.70], support_modelfree)
    recalls = [cm.recall for _, cm in res]
    # eşik yükseldikçe recall artmaz (monoton azalır/sabit)
    assert recalls[0] >= recalls[1] >= recalls[2]


def test_separation_positive_gap_when_supported_scores_higher():
    scores = [
        _cs("p1", True, True, 0.80, 0.0),
        _cs("p2", True, True, 0.70, 0.0),
        _cs("n1", False, True, 0.30, 0.0),
        _cs("n2", False, True, 0.20, 0.0),
    ]
    mean_pos, mean_neg, gap = separation(scores, lambda cs: cs.fuzzy)
    assert mean_pos == pytest.approx(0.75)
    assert mean_neg == pytest.approx(0.25)
    assert gap == pytest.approx(0.50)


# --------------------------------------------------------------------------
#  Verdict karakterizasyonu (MIN_VERIFIED_CLAIMS_RATIO)
# --------------------------------------------------------------------------

def test_verdict_table_min_ratio_boundary():
    table = verdict_table([0.20, 0.50], [0.1, 0.2, 0.5, 1.0])
    by_min = dict(table)
    # MIN_RATIO=0.20: 0.2 oranı pass, 0.1 retry (retry hakkı var)
    row_020 = dict(by_min[0.20])
    assert row_020[0.2] == "pass"
    assert row_020[0.1] == "retry"
    assert row_020[1.0] == "pass"
    # MIN_RATIO=0.50: 0.2 artık pass DEĞİL → retry
    row_050 = dict(by_min[0.50])
    assert row_050[0.2] == "retry"
    assert row_050[0.5] == "pass"


def test_verdict_table_restores_module_global():
    import agents.nodes.verify as _v

    before = _v.MIN_VERIFIED_CLAIMS_RATIO
    verdict_table([0.99], [0.5])
    # geçici monkeypatch sonrası orijinal değer geri yüklenmeli
    assert before == _v.MIN_VERIFIED_CLAIMS_RATIO


# --------------------------------------------------------------------------
#  NLI tam-pipeline karar mantığı (saf fonksiyon — model GEREKMEZ)
# --------------------------------------------------------------------------

def test_contradiction_detected_threshold():
    assert contradiction_detected(0.70, 0.70) is True
    assert contradiction_detected(0.69, 0.70) is False


def test_support_full_contradiction_vetoes_despite_high_fuzzy():
    # yüksek fuzzy AMA NLI çelişki → veto (negation tuzağı)
    cs = _cs("a", False, l1=True, fuzzy=0.90, lettuce=0.5)
    assert support_full(cs, ent=0.1, con=0.85,
                        fuzzy_th=0.55, nli_ent_th=0.55, contra_th=0.70) is False


def test_support_full_entailment_recovers_low_fuzzy_paraphrase():
    # fuzzy eşik altı ama NLI entailment yüksek → desteklenir
    cs = _cs("b", True, l1=True, fuzzy=0.40, lettuce=0.0)
    assert support_full(cs, ent=0.80, con=0.05,
                        fuzzy_th=0.55, nli_ent_th=0.55, contra_th=0.70) is True


def test_support_full_format_fail_blocks_everything():
    cs = _cs("c", False, l1=False, fuzzy=0.99, lettuce=0.99)
    assert support_full(cs, ent=0.99, con=0.0,
                        fuzzy_th=0.55, nli_ent_th=0.55, contra_th=0.70) is False


def test_build_nli_section_structure_with_fake_scores():
    scores = [
        _cs("EX", True, l1=True, fuzzy=0.80, lettuce=0.7, cat="exact"),
        _cs("CON", False, l1=True, fuzzy=0.75, lettuce=0.5, cat="contradiction"),
    ]
    # CON: NLI çelişki yüksek → veto; EX: entailment yüksek → destek
    fake_nli = {
        "EX": (0.85, 0.02, "entailment"),
        "CON": (0.05, 0.92, "contradiction"),
    }
    section = build_nli_section(scores, fake_nli)
    fp = section["full_pipeline"]
    # EX doğru destek (TP), CON doğru veto (TN) → mükemmel
    assert fp["tp"] == 1
    assert fp["tn"] == 1
    assert fp["fp"] == 0
    assert fp["fn"] == 0
    # çelişki taramasında 0.70 eşiğinde CON yakalanmalı, EX'e yanlış-veto olmamalı
    sweep_070 = next(r for r in section["contradiction_threshold_sweep"] if r["th"] == 0.70)
    assert sweep_070["contradiction_recall"] == 1.0
    assert sweep_070["false_veto_on_supported"] == 0


# --------------------------------------------------------------------------
#  Skorlama (deterministik katman çağrısı — model yok)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_case_faithful_high_fuzzy():
    gc = GoldCase(
        id="t1", category="exact", should_support=True,
        claim_text="Kiracı kira ilişkisi sona erdiğinde depozitosunu geri alır.",
        cite_ids=("c1",),
        evidence=(
            {"source_id": "c1", "title": "Depozito",
             "snippet": "Kira ilişkisi sona erdiğinde kiracı depozitosunu geri alır."},
        ),
    )
    cs = await score_case(gc)
    assert cs.l1_ok is True
    assert cs.fuzzy >= 0.55  # yüksek örtüşme
    assert 0.0 <= cs.lettuce <= 1.0


@pytest.mark.asyncio
async def test_score_case_unsupported_low_fuzzy():
    gc = GoldCase(
        id="t2", category="unsupported", should_support=False,
        claim_text="Apollo görevi aya iniş yaptı.",
        cite_ids=("c1",),
        evidence=(
            {"source_id": "c1", "title": "Depozito",
             "snippet": "Kira ilişkisi sona erdiğinde kiracı depozitosunu geri alır."},
        ),
    )
    cs = await score_case(gc)
    # alakasız → fuzzy düşük
    assert cs.fuzzy < 0.55


@pytest.mark.asyncio
async def test_score_case_format_bad_l1_fails():
    gc = GoldCase(
        id="t3", category="format_bad", should_support=False,
        claim_text="İlgili maddede belirtildiği gibi haklısınız.",
        cite_ids=("c1",),
        evidence=(
            {"source_id": "c1", "title": "X",
             "snippet": "Tüketici sözleşmeden dönme hakkına sahiptir."},
        ),
    )
    cs = await score_case(gc)
    # "madde" kökü var ama numara yok → L1 başarısız
    assert cs.l1_ok is False


# --------------------------------------------------------------------------
#  Altın küme + rapor entegrasyonu
# --------------------------------------------------------------------------

def test_load_gold_parses_dataset():
    cases = load_gold()
    assert len(cases) >= 20
    cats = {c.category for c in cases}
    assert {"exact", "paraphrase", "unsupported", "contradiction", "format_bad"} <= cats
    # her vakada zorunlu alanlar dolu
    for c in cases:
        assert c.claim_text
        assert c.evidence


@pytest.mark.asyncio
async def test_build_report_structure():
    cases = load_gold()
    scores = [await score_case(c) for c in cases]
    report = build_report(scores)
    assert report["n_cases"] == len(cases)
    assert "current_modelfree" in report
    assert "fuzzy_sweep" in report
    assert len(report["fuzzy_sweep"]) == 7
    assert "per_category" in report
    # mevcut eşikte format_bad kategorisi tam doğru sınıflanmalı (hepsi reddedilir)
    assert report["per_category"]["format_bad"]["decision_accuracy"] == 1.0
