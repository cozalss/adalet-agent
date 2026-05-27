"""Triaj olgu çıkarımı (Step-3 AKIL YÜRÜTME) — _parse_triage_json + _sanitize_facts.

facts alanı additive: domain sınıflandırmasını ETKİLEMEZ, eksik/bozuk olursa
boş dict döner. Yalnız izinli anahtarlar + kısa string değerler tutulur.
"""

from __future__ import annotations

import json

from agents.nodes import triaj as triaj_mod


def test_parse_extracts_valid_facts():
    raw = json.dumps({
        "domain": "isHukuku", "confidence": 0.95, "reasoning": "işten çıkarma",
        "facts": {"sure": "3 ay", "olay": "işten çıkarıldı", "taraf": "işçi"},
    }, ensure_ascii=False)
    domain, _conf, _reason, facts = triaj_mod._parse_triage_json(raw)
    assert domain == "isHukuku"
    assert facts == {"sure": "3 ay", "olay": "işten çıkarıldı", "taraf": "işçi"}


def test_parse_missing_facts_returns_empty_dict():
    """facts alanı yoksa domain bozulmadan boş dict döner (geriye uyumlu)."""
    raw = json.dumps({"domain": "kira", "confidence": 0.8, "reasoning": "x"})
    domain, _conf, _reason, facts = triaj_mod._parse_triage_json(raw)
    assert domain == "kira"
    assert facts == {}


def test_parse_bad_json_returns_unknown_empty_facts():
    domain, _conf, _reason, facts = triaj_mod._parse_triage_json("bu json değil {{{")
    assert domain == "unknown"
    assert facts == {}


def test_sanitize_drops_unknown_keys():
    """LLM serbest/halüsinasyon anahtar üretirse izinli olmayanlar atılır."""
    out = triaj_mod._sanitize_facts({
        "sure": "2 yıl", "uydurma_alan": "zararlı", "olay": "tahliye",
    })
    assert out == {"sure": "2 yıl", "olay": "tahliye"}


def test_sanitize_drops_null_like_values():
    out = triaj_mod._sanitize_facts({
        "sure": "null", "isci_sayisi": "yok", "tutar": "-", "olay": "kira artışı",
    })
    assert out == {"olay": "kira artışı"}


def test_sanitize_non_dict_returns_empty():
    assert triaj_mod._sanitize_facts(None) == {}
    assert triaj_mod._sanitize_facts("string") == {}
    assert triaj_mod._sanitize_facts(["liste"]) == {}


def test_sanitize_truncates_long_value():
    long_val = "a" * 500
    out = triaj_mod._sanitize_facts({"olay": long_val})
    assert len(out["olay"]) == triaj_mod._MAX_FACT_VALUE_LEN
