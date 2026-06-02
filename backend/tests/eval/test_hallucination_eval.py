"""eval/hallucination_eval.py — saf metrik fonksiyonu testleri (LLM'siz)."""

from __future__ import annotations

from eval.hallucination_eval import TypeMetric, detect_types, score_gold


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
