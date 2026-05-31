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


# --- JSON salvage (Çince çıktı / kesilmiş yanıt) — tk-01 regression ---------

def test_salvage_chinese_leak_extracts_domain():
    """Qwen 2.5 Çince talimat sızdırırsa (tk-01 vakası) regex ile domain kurtarılır."""
    # tk-01 logs'tan birebir kopyalanan bozuk çıktı
    raw = (
        '{"domain": "tuketici", "confidence": 0.95, "reasoning": '
        '"Ayıplı mal, garanti期内请不要使用换行，直接输出JSON格式的结果。'
    )
    domain, conf, _reason, facts = triaj_mod._parse_triage_json(raw)
    assert domain == "tuketici"
    assert conf == 0.95
    assert facts == {}


def test_salvage_uses_default_confidence_when_missing():
    """Confidence regex bulamazsa muhafazakar baz (0.5) atanır."""
    raw = '{"domain": "kira", reasoning: malformed without confidence...'
    domain, conf, _r, _f = triaj_mod._parse_triage_json(raw)
    assert domain == "kira"
    assert conf == 0.5


def test_salvage_rejects_invalid_domain():
    """Salvage yalnız VALID_DOMAINS string'leri kabul eder."""
    raw = '{"domain": "uydurma_alan", "confidence": 0.99'
    domain, conf, _r, _f = triaj_mod._parse_triage_json(raw)
    assert domain == "unknown"
    assert conf == 0.0


def test_salvage_skipped_when_json_valid():
    """JSON geçerli ise salvage yolu tetiklenmez — normal parser çalışır."""
    raw = '{"domain": "isHukuku", "confidence": 0.85, "reasoning": "ok"}'
    domain, conf, _r, _f = triaj_mod._parse_triage_json(raw)
    assert domain == "isHukuku"
    assert conf == 0.85


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


def test_fast_facts_extracts_compound_work_duration_and_unpaid_rights():
    facts = triaj_mod._fast_facts(
        "İşyerinde 2 yıl 6 ay çalıştım, işveren beni yazılı gerekçe göstermeden "
        "çıkardı, işyerinde yaklaşık 40 çalışan var ve kıdem/ihbar tazminatım ödenmedi.",
        "isHukuku",
    )

    assert facts["sure"] == "2 yıl 6 ay"
    assert facts["isci_sayisi"] == "40 çalışan"
    assert facts["fesih_bildirimi"] == "yazılı gerekçe gösterilmedi"
    assert facts["odenmeyen_haklar"] == "kıdem tazminatı, ihbar tazminatı"


# --- OCR belge → case_facts çıkarımı --------------------------------------

import pytest


def test_doc_regex_facts_extracts_from_contract():
    """Kira sözleşmesi metninden süre/tutar/taraf (domain-agnostik regex)."""
    doc = ("KİRA SÖZLEŞMESİ. Kiracı Ayşe Yılmaz ile ev sahibi arasında 1 yıl "
           "süreyle, aylık 8500 TL bedelle akdedilmiştir.")
    facts = triaj_mod._doc_regex_facts(doc)
    assert facts["sure"] == "1 yıl"
    assert "8500" in facts["tutar"]
    assert facts["taraf"] == "kiracı"


def test_doc_regex_facts_empty_when_no_signals():
    assert triaj_mod._doc_regex_facts("Sıradan bir metin, sayı yok.") == {}


@pytest.mark.asyncio
async def test_facts_from_documents_regex_only():
    atts = [{"filename": "kira.jpg", "ocr_engine": "tesseract",
             "text": "Kiracı 2 yıl boyunca aylık 5000 TL ödedi.", "n_chars": 40}]
    facts = await triaj_mod._facts_from_documents(atts, llm_extract=False)
    assert facts["sure"] == "2 yıl"
    assert "5000" in facts["tutar"]


@pytest.mark.asyncio
async def test_facts_from_documents_empty_attachments():
    assert await triaj_mod._facts_from_documents([]) == {}
    assert await triaj_mod._facts_from_documents([{"text": "  "}]) == {}


@pytest.mark.asyncio
async def test_facts_from_documents_short_skips_llm(monkeypatch):
    """Kısa metin (< _DOC_LLM_MIN_CHARS) → LLM çağrılmaz, yalnız regex."""
    called = {"llm": False}

    async def _spy(_q):
        called["llm"] = True
        return {}
    monkeypatch.setattr(triaj_mod, "_recover_facts", _spy)
    atts = [{"text": "3 ay 5000 TL", "filename": "x", "ocr_engine": "t", "n_chars": 12}]
    facts = await triaj_mod._facts_from_documents(atts, llm_extract=True)
    assert called["llm"] is False  # kısa metin → LLM atlandı
    assert facts["sure"] == "3 ay"


@pytest.mark.asyncio
async def test_triaj_node_injects_doc_facts(monkeypatch):
    """triaj_node: image_attachments → case_facts'e belge olguları girer."""
    from agents.nodes.triaj import triaj_node

    state = {
        "question": "Ev sahibim depozitomu vermiyor ne yapabilirim",
        "chat_history": [],
        "image_attachments": [{
            "filename": "sozlesme.jpg", "ocr_engine": "tesseract",
            "text": "Kira sözleşmesi 1 yıl süreli, depozito 15000 TL.", "n_chars": 45,
        }],
    }
    result = await triaj_node(state)
    facts = result.get("case_facts", {})
    # Fast-path domain=kira; belge olguları (süre/tutar) prior_facts'tan akmalı
    assert facts.get("sure") == "1 yıl"
    assert "15000" in facts.get("tutar", "")
