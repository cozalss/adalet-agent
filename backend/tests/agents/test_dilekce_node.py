"""dilekce_node guard'ları ve happy path testleri."""

from __future__ import annotations

import pytest

from agents.nodes.dilekce import dilekce_node
from agents.state import AgentState, Citation, Claim


def _state(**overrides) -> AgentState:
    base: dict = {
        "question": "Aldığım telefonun şarjı dayanmıyor.",
        "want_dilekce": True,
        "domain": "tuketici",
        "debate_verdict": "pass",
        "case_facts": {"olay": "şarj arızası", "taraf": "tüketici"},
        "verified_claims": [
            Claim(
                text="Tüketici, garanti süresi içinde değişim talep edebilir.",
                cite_ids=["m-TKHK-11"], verified=True,
                verify_score=0.9, verify_reason="ok",
            ),
        ],
        "mevzuat_refs": [
            Citation(
                source_id="m-TKHK-11", title="TKHK Madde 11",
                url="https://mevzuat.gov.tr/x", snippet="...", score=0.9, doc_type="law",
            ),
        ],
        "emsal_refs": [],
        "user_meta": {"sehir": "Ankara"},
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_dilekce_node_happy_path_produces_pdf():
    result = await dilekce_node(_state())
    assert "dilekce_pdf_bytes" in result
    assert result["dilekce_pdf_bytes"].startswith(b"%PDF-")
    assert result["dilekce_template_id"].startswith("tuketici/")
    assert result["dilekce_filename"].endswith(".pdf")
    assert "dilekce_md" in result and len(result["dilekce_md"]) > 200


@pytest.mark.asyncio
async def test_dilekce_node_skips_when_want_dilekce_false():
    result = await dilekce_node(_state(want_dilekce=False))
    assert result == {}


@pytest.mark.asyncio
async def test_dilekce_node_skips_when_verdict_reject():
    result = await dilekce_node(_state(debate_verdict="reject"))
    assert result == {}


@pytest.mark.asyncio
async def test_dilekce_node_skips_when_domain_unknown():
    result = await dilekce_node(_state(domain="unknown"))
    assert result == {}


@pytest.mark.asyncio
async def test_dilekce_node_skips_when_no_verified_claims():
    """Sıfır halüsinasyon: verified claim yoksa dilekçe üretilmez."""
    state = _state(verified_claims=[
        Claim(text="x", cite_ids=[], verified=False, verify_score=0.0, verify_reason=""),
    ])
    result = await dilekce_node(state)
    assert result == {}


@pytest.mark.asyncio
async def test_dilekce_node_skips_when_no_mevzuat():
    """Hukuki dayanak yoksa dilekçe üretilmez (kaynaksız iddia atılmaz)."""
    result = await dilekce_node(_state(mevzuat_refs=[]))
    assert result == {}


@pytest.mark.asyncio
async def test_dilekce_node_picks_correct_template_for_keyword():
    """case_facts/soruda 'ayıplı' geçerse ayipli_mal_iade template seçilmeli."""
    state = _state(question="Aldığım buzdolabı ayıplı çıktı, ne yapabilirim?")
    result = await dilekce_node(state)
    # tuketici/ayipli_mal_iade_v1 daha yüksek keyword puan alır
    assert result["dilekce_template_id"] == "tuketici/ayipli_mal_iade_v1"


@pytest.mark.asyncio
async def test_dilekce_node_kvkk_no_real_tc_in_output():
    """user_meta'da TC yoksa, render edilen md'de placeholder kalmalı, gerçek TC YAZILMAZ."""
    result = await dilekce_node(_state(user_meta={"sehir": "Ankara"}))
    md = result["dilekce_md"]
    # 11-haneli rakam dizgisi olmamalı (TCKN regex)
    import re
    assert not re.search(r"\b\d{11}\b", md), "11-haneli sayı (gerçek TC) sızıntısı!"
    # Placeholder korunmalı
    assert "[T.C. KİMLİK NO]" in md
