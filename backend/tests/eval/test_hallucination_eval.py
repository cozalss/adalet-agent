"""eval/hallucination_eval.py — saf metrik fonksiyonu testleri (LLM'siz)."""

from __future__ import annotations

from pathlib import Path

from eval.answer_risk import unsourced_legal_claims
from eval.hallucination_eval import TypeMetric, detect_types, load_gold, score_gold

_REAL_GOLD = (
    Path(__file__).resolve().parents[2]
    / "data" / "eval_benchmark" / "hallucination_gold.jsonl"
)


def test_detect_types_fabricated_law():
    assert "fabricated_law" in detect_types("İşçilik Kanunu'na göre tazminat ödenir [src: m-IK-14].")


def test_detect_types_fabricated_citation():
    assert "fabricated_citation" in detect_types("Yargıtay 99. Hukuk Dairesi kararı emsaldir.")


def test_detect_types_clean_answer_empty():
    clean = "İş Kanunu madde 14 uyarınca kıdem tazminatı ödenir [src: m-IK-14]."
    assert detect_types(clean) == set()


def test_type_metric_math():
    m = TypeMetric("x", tp=8, fp=2, fn=0)
    assert m.precision == 0.8
    assert m.recall == 1.0
    assert m.f1 == round(2 * 0.8 / 1.8, 3)


def test_type_metric_no_predictions_is_precise():
    m = TypeMetric("x", tp=0, fp=0, fn=0)
    assert m.precision == 1.0 and m.recall == 1.0


def test_score_gold_perfect_detection():
    rows = [
        {"id": "1", "answer": "İşçilik Kanunu'na göre tazminat [src: m-IK-1].",
         "types": ["fabricated_law"], "is_clean": False},
        {"id": "2", "answer": "Yargıtay 99. Hukuk Dairesi kararı.",
         "types": ["fabricated_citation"], "is_clean": False},
        {"id": "3", "answer": "İş Kanunu madde 14 uyarınca tazminat ödenir [src: m-IK-14].",
         "types": [], "is_clean": True},
    ]
    s = score_gold(rows)
    assert s["veto_false_positives"] == 0
    assert s["hallucination_recall"] == 1.0
    assert s["per_type"]["fabricated_law"]["recall"] == 1.0
    assert s["per_type"]["fabricated_citation"]["recall"] == 1.0


def test_score_gold_counts_veto_false_positive():
    # Temiz işaretlenmiş ama veto tetikleyen cevap → veto_false_positives sayılır.
    rows = [{"id": "bad", "answer": "İşçilik Kanunu hükmü uygulanır.", "types": [], "is_clean": True}]
    s = score_gold(rows)
    assert s["veto_false_positives"] == 1


# --- ADVERSARIAL GOLD SETİ — yarışma kanıt-tablosu regresyon kapısı (iter-3) ---


def test_real_gold_set_is_adversarial_scale():
    """Gold set yeterince geniş ve adversarial: ≥100 vaka, hem temiz hem riskli sınıf.

    'Halüsinasyon gold seti dar (40 satır)' boşluğunun (denetim 2026-06-03) kapanma kanıtı.
    """
    rows = load_gold(str(_REAL_GOLD))
    assert len(rows) >= 100, f"adversarial set küçülmüş: {len(rows)}"
    assert sum(1 for r in rows if r.get("is_clean")) >= 25  # hard-negative kapsamı
    assert sum(1 for r in rows if not r.get("is_clean")) >= 60  # halüsinasyon kapsamı


def test_real_gold_set_zero_false_veto_and_full_recall():
    """KRİTİK: 104 adversarial vakada temiz cevap ASLA reddedilmez (veto_fp=0) ve
    her riskli cevap yakalanır (recall=1.0). 'Sıfır halüsinasyon + valid'i bozma' kanıtı."""
    s = score_gold(load_gold(str(_REAL_GOLD)))
    assert s["veto_false_positives"] == 0, "valid cevabı reddetmek = kabul edilemez"
    assert s["hallucination_recall"] == 1.0
    assert s["micro_precision"] == 1.0


def test_unsourced_detector_robust_to_turkish_inflection():
    """Detektör Türkçe iyelik/mastar çekimine dayanıklı: 'tahliye davası açabilir'
    ('dava aç' değil 'davası aç') ve 'talep etme' ('talep ed' değil 'talep et')."""
    assert unsourced_legal_claims("Kiracı tahliye davası açabilir ve depozitosunu geri alabilir.")
    assert unsourced_legal_claims("Tüketici ücretsiz onarım talep etme imkânına sahiptir.")
    # kaynaklı (temiz) aynı çekim → bayraklanmaz (false-positive guard)
    assert unsourced_legal_claims("Tahliye davası açabilirsiniz [src: m-TBK-347].") == []
