"""Dilekçe template_registry — select_template_id davranış testleri."""

from __future__ import annotations

from agents.dilekce.template_registry import (
    _REGISTRY,
    available_templates,
    select_template_id,
    template_label,
)


def test_all_8_domains_have_templates():
    """Mevcut 8 hukuk alanı + unknown — toplam 9 anahtar."""
    expected = {"tuketici", "isHukuku", "kira", "icra", "trafik", "vergi", "tapu", "idari"}
    real = set(_REGISTRY) - {"unknown"}
    assert real == expected


def test_each_real_domain_has_at_least_two_templates():
    for domain in ("tuketici", "isHukuku", "kira", "icra", "trafik", "vergi", "tapu", "idari"):
        assert len(available_templates(domain)) >= 2, f"{domain}: yetersiz template"


def test_unknown_domain_returns_none():
    assert select_template_id("unknown", "soru") is None


def test_keyword_match_picks_ayipli_template():
    tid = select_template_id("tuketici", "buzdolabım ayıplı çıktı")
    assert tid == "tuketici/ayipli_mal_iade_v1"


def test_keyword_match_picks_kidem_template():
    tid = select_template_id("isHukuku", "3 yıl çalıştım kıdem tazminatı")
    assert tid == "isHukuku/kidem_tazminat_talep_v1"


def test_no_match_falls_to_first_template():
    """Hiç eşleşme yoksa registry'deki ilk template seçilir."""
    tid = select_template_id("vergi", "garip soru")
    assert tid == "vergi/vergi_ceza_itiraz_v1"     # registry sırasında ilk


def test_case_facts_used_in_scoring():
    """case_facts.olay 'haciz' keyword'ü ile haciz_kaldirma seçilmeli."""
    tid = select_template_id("icra", "borç sorum", {"olay": "maaşa haciz geldi"})
    assert tid == "icra/haciz_kaldirma_v1"


def test_template_label_returns_human_readable():
    label = template_label("tuketici/hakem_heyeti_basvuru_v1")
    assert "Hakem Heyet" in label
    # Bilinmeyen id → id'nin kendisi (graceful fallback)
    assert template_label("uydurma/x") == "uydurma/x"
