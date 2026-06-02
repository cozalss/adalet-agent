"""scripts/predictive/build_gold_eval.py — saf çekirdek (parse + agreement). LLM GEREKMEZ."""

from __future__ import annotations

from scripts.predictive.build_gold_eval import (
    agreement_stats,
    extract_full_hukum,
    parse_adjudication,
)


def test_extract_full_hukum_from_header():
    text = "Olay kısmı uzun metin. HÜKÜM: davanın kabulüne oybirliğiyle karar verildi."
    h = extract_full_hukum(text)
    assert h.startswith("HÜKÜM") and "kabulüne" in h  # tam hüküm, cased, başlıktan sona


def test_extract_full_hukum_no_header_tail():
    text = "x" * 5000  # başlık yok → son kısım (tail) döner
    h = extract_full_hukum(text, cap=4000)
    assert len(h) <= 4000 and len(h) > 0


def test_parse_valid_json():
    assert parse_adjudication('{"label": "kazandi", "quote": "kabulüne"}') == ("kazandi", "kabulüne")


def test_parse_extracts_embedded_json():
    raw = 'Düşünce... {"label":"kismi","quote":"kısmen kabul"} sonu.'
    assert parse_adjudication(raw) == ("kismi", "kısmen kabul")


def test_parse_invalid_label_is_none():
    assert parse_adjudication('{"label": "iptal", "quote": "x"}') is None


def test_parse_belirsiz_valid():
    assert parse_adjudication('{"label": "belirsiz", "quote": ""}') == ("belirsiz", "")


def test_parse_garbage_is_none():
    assert parse_adjudication("metin, json yok") is None
    assert parse_adjudication("") is None


def test_agreement_overall_and_per_class():
    pairs = [("kazandi", "kazandi"), ("kazandi", "kaybetti"),
             ("kaybetti", "kaybetti"), ("kismi", "kismi")]
    s = agreement_stats(pairs)
    assert s["n"] == 4
    assert s["overall"] == 0.75
    assert s["per_silver"]["kazandi"]["agree"] == 0.5
    assert s["per_silver"]["kaybetti"]["agree"] == 1.0


def test_agreement_empty():
    assert agreement_stats([])["overall"] == 0.0
