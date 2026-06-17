"""Triaj olgu çıkarımı (Step-3 AKIL YÜRÜTME) — _parse_triage_json + _sanitize_facts.

facts alanı additive: domain sınıflandırmasını ETKİLEMEZ, eksik/bozuk olursa
boş dict döner. Yalnız izinli anahtarlar + kısa string değerler tutulur.
"""

from __future__ import annotations

import json

import pytest

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


def test_fast_facts_broad_markers_trafik_vergi_idari():
    """Genişletilmiş marker'lar doğal-dil sorularda olay çıkarır (gereksiz clarify önlenir, 2026-06-04)."""
    from agents.nodes.triaj import _fast_facts
    assert _fast_facts("Park halindeyken aracıma çarpıp kaçtılar, kamera var", "trafik").get("olay")
    assert _fast_facts("Adıma fazladan emlak vergisi tahakkuk ettirilmiş, itiraz", "vergi").get("olay")
    assert _fast_facts("Memuruyken disiplin cezasıyla görevden uzaklaştırıldım", "idari").get("olay")


def test_fast_facts_vague_question_still_clarifies():
    """Belirsiz soru olay ÇIKARMAMALI → clarify korunur (over-answer önlenir)."""
    from agents.nodes.triaj import _fast_facts
    assert not _fast_facts("vergi konusunda genel bir sorum olacaktı", "vergi").get("olay")


def test_is_minor_first_person_only():
    """Çocuk filtresi (CLAUDE.md §4) yalnız 1. tekil şahıs <18 — ebeveyn/18+/selam yanlış-pozitif YOK."""
    from agents.nodes.triaj import _is_minor
    assert _is_minor("ben 15 yaşındayım, ne yapmalıyım")
    assert _is_minor("reşit değilim, yardım eder misiniz")
    assert not _is_minor("kızım 15 yaşında, hakkı var mı")   # ebeveyn (yetişkin)
    assert not _is_minor("18 yaşındayım, çalışabilir miyim")  # reşit
    assert not _is_minor("25 yaşındayım")
    assert not _is_minor("merhaba nasılsın")


def test_chat_disclaimer_only_for_legal_hint():
    """Chat disclaimer (CLAUDE.md §2): hukuki kavramda eklenir, saf selamda eklenmez."""
    from agents.nodes.finalize import _chat_needs_disclaimer
    assert _chat_needs_disclaimer("kıdem tazminatı nedir", "Kıdem tazminatı işçinin hakkıdır.")
    assert not _chat_needs_disclaimer("selam", "İyiyim, teşekkürler. Sen nasılsın?")


# --- _merge_case_facts: 'olay' birikir, sayısal olgular override ---

def test_merge_case_facts_olay_accumulates_across_turns():
    """Multi-turn: önceki turun 'olay'ı + yeni tur 'olay' → İKİSİ DE korunur (birikim)."""
    out = triaj_mod._merge_case_facts(
        {"olay": "4 aydır kiracıyım kira 8000"},
        {"olay": "ev sahibi artış yaptı"},
    )
    assert out["olay"] == "4 aydır kiracıyım kira 8000; ev sahibi artış yaptı"


def test_merge_case_facts_numeric_overrides():
    """Sayısal olgular (süre/tutar) yeni değerle ÜZERİNE yazılır (birikmez)."""
    out = triaj_mod._merge_case_facts({"sure": "2 yıl", "tutar": "8000"}, {"sure": "3 yıl"})
    assert out["sure"] == "3 yıl"        # override
    assert out["tutar"] == "8000"        # korunur


def test_merge_case_facts_olay_dedup_no_double():
    """Aynı 'olay' iki kez gelirse tekrar EKLENMEZ (çift yok)."""
    out = triaj_mod._merge_case_facts({"olay": "depozito iadesi"}, {"olay": "depozito iadesi"})
    assert out["olay"] == "depozito iadesi"


def test_merge_case_facts_olay_cap_300():
    """Biriken 'olay' geniş cap'te (300) kırpılır — sayısal 120 cap'ten farklı."""
    a, b = "x" * 200, "y" * 200
    out = triaj_mod._merge_case_facts({"olay": a}, {"olay": b})
    assert len(out["olay"]) == 300


# --- _fast_domain: trafik keyword kapsamı (iter7 sweep'te 'kırmızı ışık' → unknown idi) ---

def test_fast_domain_trafik_kirmizi_isik_and_no_cross_domain():
    """Ölçülen gap: 'kırmızı ışık cezasına itiraz' artık trafik yakalanır; çakışma yok."""
    assert triaj_mod._fast_domain("kırmızı ışık cezasına nasıl itiraz edebilirim") == "trafik"
    assert triaj_mod._fast_domain("hız cezası radar") == "trafik"
    assert triaj_mod._fast_domain("araç muayene cezası geldi") == "trafik"
    # mtv vergi'de kalmalı (trafik'e eklenmedi — çakışma önlendi)
    assert triaj_mod._fast_domain("mtv borcumu ödemedim") == "vergi"
    assert triaj_mod._fast_domain("emlak vergisi gecikme cezası") == "vergi"


# --- Tüketici domain robustness (2026-06-17 prod-bug: 'telefonum bzuldu dün almıştım'
#     → unknown → kapsam-dışı red). Ürün-ismi çapası + satın-alma×arıza kombosu. ---

def test_consumer_complaint_combo():
    """Satın-alma + arıza birlikte → tüketici (keyword-dışı ürünleri de yakalar)."""
    f = triaj_mod._is_consumer_complaint
    assert f(triaj_mod._tr_lower("fırınım bozuldu dün aldım")) is True
    assert f(triaj_mod._tr_lower("internetten aldığım ayakkabı defolu çıktı")) is True
    # Tek başına satın-alma (ev aldım → tapu) veya tek başına arıza → tetiklemez
    assert f(triaj_mod._tr_lower("ev aldım tapuda sorun var")) is False
    assert f(triaj_mod._tr_lower("evliliğim bozuldu")) is False


def test_fast_domain_consumer_product_anchor():
    """Ürün-ismi domain çapası: arıza fiili typo'lansa bile ('bzuldu') domain bulunur."""
    fd = triaj_mod._fast_domain
    assert fd("telefonum bzuldu dün almıştım") == "tuketici"   # typo → 'telefon' çapa
    assert fd("buzdolabım çalışmıyor garanti var mı") == "tuketici"
    assert fd("fırınım bozuldu dün aldım") == "tuketici"        # kombo (keyword-dışı ürün)


def test_fast_domain_typo_tolerant_legal_keywords():
    """ASCII/eksik-harfli vatandaş sorguları hızlı triajda domain kaçırmamalı."""
    fd = triaj_mod._fast_domain
    assert fd("isden cikarildim kidem tazmnatı alabilir miyim") == "isHukuku"
    assert fd("tuketici hakem heyetine basvurmak istiyorum") == "tuketici"
    assert fd("kira artisinda tufe siniri nedir") == "kira"
    assert fd("iseiade davası acabilir miyim") == "isHukuku"


def test_out_of_scope_typo_tolerant_family_law():
    """Kapsam-dışı aile hukuku ASCII yazılsa da yakalanır."""
    assert triaj_mod._is_out_of_scope("bosanma davası ve nafaka sorum var") is True


def test_fast_domain_no_cross_domain_false_positive():
    """Tüketici sinyalleri başka domain'leri/off-topic'i çalmamalı."""
    fd = triaj_mod._fast_domain
    assert fd("ev sahibim depozitomu vermiyor") == "kira"
    assert fd("işten çıkarıldım kıdem tazminatı") == "isHukuku"
    # 'evliliğim bozuldu' (aile, kapsam-dışı): tüketici'ye KAYMAMALI
    assert fd("evliliğim bozuldu") != "tuketici"
    # FP guard: çıplak ürün-ismi (satın-alma/arıza YOK) → tüketici DEĞİL
    assert fd("telefon numaranı verir misin") != "tuketici"
    assert triaj_mod._is_consumer_complaint(triaj_mod._tr_lower("telefon numaranı verir misin")) is False


def test_fast_facts_consumer_extracts_olay():
    """Kısa tüketici şikâyetinde 'olay' çıkar → policy answer (clarify değil)."""
    ff = triaj_mod._fast_facts
    assert ff("telefonum bozuldu dün aldım", "tuketici").get("olay")
    assert ff("fırınım bozuldu dün aldım", "tuketici").get("olay")
    assert ff("telefonum bzuldu dün almıştım", "tuketici").get("olay")  # typo → 'almıştım'
