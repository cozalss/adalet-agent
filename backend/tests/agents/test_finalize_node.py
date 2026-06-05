"""finalize_node — fail-closed ama kapsam-koruyan cümle-eleme testleri."""

from __future__ import annotations

import pytest

from agents.nodes.finalize import (
    _format_citations,
    _remove_orphan_source_tags,
    _split_sentences,
    finalize_node,
)


def _asciiish(text: str) -> str:
    return text.translate(str.maketrans({
        "ç": "c", "Ç": "C",
        "ğ": "g", "Ğ": "G",
        "ı": "i", "I": "I",
        "İ": "I", "i": "i",
        "ö": "o", "Ö": "O",
        "ş": "s", "Ş": "S",
        "ü": "u", "Ü": "U",
    })).lower()


@pytest.mark.asyncio
async def test_finalize_strips_unverified_keeps_verified(base_state):
    """Bazı claim'ler doğrulanmamışsa: tüm cevap reddedilmez — doğrulanmamış
    cümle ATILIR, doğrulanmış cümle KORUNUR (kapsam-koruyan fail-closed)."""
    claims = [
        {
            "text": "Destekli iddia cümlesi yeterince uzun olmalı burada",
            "cite_ids": ["m-TKHK-11"],
            "verified": False, "verify_score": 0.0, "verify_reason": "",
        },
        {
            "text": "Desteksiz uydurma iddia cümlesi de yeterince uzun olmalı",
            "cite_ids": [],
            "verified": False, "verify_score": 0.0, "verify_reason": "",
        },
    ]
    verified_claims = [
        {**claims[0], "verified": True, "verify_score": 0.9, "verify_reason": "ok"},
        {**claims[1], "verified": False, "verify_score": 0.1, "verify_reason": "Yetersiz kanıt"},
    ]
    state = {
        **base_state,
        "draft_response": (
            "Destekli iddia cümlesi yeterince uzun olmalı burada. "
            "Desteksiz uydurma iddia cümlesi de yeterince uzun olmalı."
        ),
        "claims": claims,
        "verified_claims": verified_claims,
        "debate_verdict": "pass",
    }

    out = await finalize_node(state)

    # Cevap reddedilmedi (kapsam korundu) ama doğrulanmamış cümle atıldı.
    assert out["confidence"] > 0.0
    assert "Destekli iddia cümlesi" in out["response"]
    assert "Desteksiz uydurma iddia" not in out["response"]


@pytest.mark.asyncio
async def test_finalize_emits_clarify_response_directly():
    """needs_clarification: hazır takip soruları doğrudan basılır — hukuki
    assembly/disclaimer YOK, reject yoluna düşmez (domain geçerli olsa bile)."""
    clarify = (
        "Daha doğru yardımcı olabilmem için birkaç bilgiye ihtiyacım var:\n\n"
        "1. Kira sözleşmesi sona erdi mi?\n2. Evi teslim ettiniz mi?"
    )
    state = {
        "domain": "kira",
        "debate_verdict": "pass",
        "response_intent": "needs_clarification",
        "clarify_response": clarify,
        "clarifying_questions": ["Kira sözleşmesi sona erdi mi?", "Evi teslim ettiniz mi?"],
    }

    out = await finalize_node(state)

    assert out["response"] == clarify
    assert out["disclaimers"] == []
    assert out["confidence"] == 0.0
    assert "Kaynaklar" not in out["response"]


@pytest.mark.asyncio
async def test_finalize_rejects_when_all_claims_unverified(base_state):
    """Hiçbir iddia doğrulanmadıysa gösterilecek güvenli içerik yok → reddet."""
    claims = [
        {
            "text": "Doğrulanamayan tek iddia cümlesi yeterince uzun",
            "cite_ids": [], "verified": False, "verify_score": 0.0, "verify_reason": "",
        },
    ]
    verified_claims = [
        {**claims[0], "verified": False, "verify_score": 0.1, "verify_reason": "Yetersiz kanıt"},
    ]
    state = {
        **base_state,
        "draft_response": "Doğrulanamayan tek iddia cümlesi yeterince uzun.",
        "claims": claims,
        "verified_claims": verified_claims,
        "debate_verdict": "pass",
    }

    out = await finalize_node(state)

    assert out["debate_verdict"] == "reject"
    assert out["confidence"] == 0.0
    assert "Bu soruya şu an net bir yanıt veremiyorum" in out["response"]


@pytest.mark.asyncio
async def test_finalize_unknown_domain_redirects_to_scope_without_disclaimer(base_state):
    state = {
        **base_state,
        "question": "Film onerir misin?",
        "domain": "unknown",
        "domain_confidence": 0.0,
        "triage_reasoning": "Kapsam disi genel soru",
    }

    out = await finalize_node(state)

    assert out["debate_verdict"] == "reject"
    assert out["confidence"] == 0.0
    assert out["disclaimers"] == []
    # Tip sözleşmesi (denetim 2026-06-04): emit edilen response_intent GEÇERLİ bir
    # ResponseIntent üyesi olmalı VE frontend'in tanıdığı 'redirect' değeri olmalı
    # (App.jsx/useChat/parseAnswer 'redirect' arar). Eski 'redirect' Literal'da yoktu.
    from typing import get_args

    from agents.state import ResponseIntent
    assert out["response_intent"] == "redirect"
    assert out["response_intent"] in get_args(ResponseIntent)
    response = _asciiish(out["response"])
    assert "guvenilir bir cevap verecek sekilde tasarlanmadim" in response
    assert "benim ana amacim" in response
    assert "hukuki durumu" in response


@pytest.mark.asyncio
async def test_finalize_drops_mixed_sentence_instead_of_leaking_unverified(base_state):
    """Aynı cümlede destekli + desteksiz iddia varsa parçalayamayız; cümle atılır."""
    claims = [
        {
            "text": "Destekli iddia bu cümlede geçiyor",
            "cite_ids": ["m-TKHK-11"],
            "verified": False,
            "verify_score": 0.0,
            "verify_reason": "",
        },
        {
            "text": "desteksiz uydurma iddia da aynı cümlede geçiyor",
            "cite_ids": [],
            "verified": False,
            "verify_score": 0.0,
            "verify_reason": "",
        },
    ]
    verified_claims = [
        {**claims[0], "verified": True, "verify_score": 0.9, "verify_reason": "ok"},
        {**claims[1], "verified": False, "verify_score": 0.1, "verify_reason": "Yetersiz kanıt"},
    ]
    state = {
        **base_state,
        "draft_response": (
            "Destekli iddia bu cümlede geçiyor ve desteksiz uydurma iddia da "
            "aynı cümlede geçiyor."
        ),
        "claims": claims,
        "verified_claims": verified_claims,
        "debate_verdict": "pass",
    }

    out = await finalize_node(state)

    assert out["debate_verdict"] == "reject"
    assert "desteksiz uydurma iddia" not in out["response"]


@pytest.mark.asyncio
async def test_finalize_treats_missing_verified_claim_as_unverified(base_state):
    """verify sonucu eksik dönerse eksik claim güvenli tarafta doğrulanmamış sayılır."""
    claims = [
        {
            "text": "Destekli iddia cümlesi burada kalmalı",
            "cite_ids": ["m-TKHK-11"],
            "verified": False,
            "verify_score": 0.0,
            "verify_reason": "",
        },
        {
            "text": "Eksik verify sonucu olan iddia burada atılmalı",
            "cite_ids": [],
            "verified": False,
            "verify_score": 0.0,
            "verify_reason": "",
        },
    ]
    verified_claims = [
        {**claims[0], "verified": True, "verify_score": 0.9, "verify_reason": "ok"},
    ]
    state = {
        **base_state,
        "draft_response": (
            "Destekli iddia cümlesi burada kalmalı. "
            "Eksik verify sonucu olan iddia burada atılmalı."
        ),
        "claims": claims,
        "verified_claims": verified_claims,
        "debate_verdict": "pass",
    }

    out = await finalize_node(state)

    assert out["confidence"] > 0.0
    assert "Destekli iddia cümlesi" in out["response"]
    assert "Eksik verify sonucu" not in out["response"]


def test_split_sentences_keeps_madde_abbreviation_together():
    text = "TKHK m. 11 tüketiciye seçimlik hak verir. ayrıca bu ayrı cümledir."

    out = _split_sentences(text)

    assert out == [
        "TKHK m. 11 tüketiciye seçimlik hak verir.",
        "ayrıca bu ayrı cümledir.",
    ]


def test_split_sentences_keeps_source_tag_with_previous_sentence():
    text = "Hak vardır. [src: m-TKHK-11]\n\nDayanak: TKHK m. 11 uygulanır."

    out = _split_sentences(text)

    assert out == [
        "Hak vardır. [src: m-TKHK-11]",
        "Dayanak: TKHK m. 11 uygulanır.",
    ]


@pytest.mark.asyncio
async def test_finalize_passes_when_all_claims_verified(base_state):
    claims = [
        {
            "text": "Tüketici ayıplı malda sözleşmeden dönebilir",
            "cite_ids": ["m-TKHK-11"],
            "verified": False,
            "verify_score": 0.0,
            "verify_reason": "",
        },
    ]
    verified_claims = [
        {**claims[0], "verified": True, "verify_score": 0.9, "verify_reason": "Fuzzy 0.90"},
    ]
    state = {
        **base_state,
        "draft_response": "Tüketici ayıplı malda sözleşmeden dönebilir [src: m-TKHK-11].",
        "claims": claims,
        "verified_claims": verified_claims,
        "debate_verdict": "pass",
    }

    out = await finalize_node(state)

    assert out["confidence"] > 0.0
    assert "Tüketici ayıplı malda" in out["response"]
    assert "Kaynaklar" in out["response"]


@pytest.mark.asyncio
async def test_finalize_rejects_retry_verdict(base_state):
    state = {**base_state, "debate_verdict": "retry", "debate_notes": "Retry limiti doldu"}

    out = await finalize_node(state)

    assert out["debate_verdict"] == "reject"
    assert out["confidence"] == 0.0
    assert "Bu konuda güvenilir bir yanıt oluşturmayı birkaç kez denedim" in out["response"]


def test_format_citations_keeps_only_cited_unique_sources(base_state):
    state = {
        **base_state,
        "draft_response": "Hak var [src: m-TKHK-11].",
        "mevzuat_refs": [
            {
                "source_id": "m-TKHK-11",
                "doc_type": "law",
                "title": "TKHK Madde 11",
                "snippet": "...",
                "url": "https://mevzuat/11",
                "score": 0.9,
            },
            {
                "source_id": "m-TKHK-11",
                "doc_type": "law",
                "title": "TKHK Madde 11 tekrar",
                "snippet": "...",
                "url": "https://mevzuat/11",
                "score": 0.8,
            },
            {
                "source_id": "m-TKHK-8",
                "doc_type": "law",
                "title": "TKHK Madde 8",
                "snippet": "...",
                "url": "https://mevzuat/8",
                "score": 0.7,
            },
        ],
        "emsal_refs": [
            {
                "source_id": "y-empty",
                "doc_type": "case",
                "title": "Yargıtay boş url",
                "snippet": "...",
                "url": "",
                "score": 0.6,
            },
        ],
    }

    out = _format_citations(state)

    assert out.count("TKHK Madde 11") == 1
    assert "TKHK Madde 8" not in out
    assert "Yargıtay boş url" not in out


def test_remove_orphan_source_tags_after_sentence_filtering():
    out = _remove_orphan_source_tags("[src: y-1]\n\nDayanak: Geçerli cümle.")

    assert out == "Dayanak: Geçerli cümle."


def test_ensure_kisacevap_header_prepends_when_first_section_lost():
    """Gövde 'Kısa cevap' DIŞI başlıkla başlıyorsa zorunlu özet eklenir (verify ilk bölümü düşürünce)."""
    from agents.nodes.finalize import _ensure_kisacevap_header
    body = "**Durumunuza uygulama:** Hakkınız var [src: m-TKHK-8].\n\n**Dayanak:** TKHK 8."
    out = _ensure_kisacevap_header(body)
    assert out.startswith("**Kısa cevap:**")
    assert "**Durumunuza uygulama:**" in out


def test_ensure_kisacevap_header_noop_when_present_or_plain():
    """Zaten 'Kısa cevap' varsa VEYA düz metin ise dokunma (çift-başlık/bozma yok)."""
    from agents.nodes.finalize import _ensure_kisacevap_header
    ok = "**Kısa cevap:** Hakkınız var."
    plain = "Hakkınız var, dava açabilirsiniz."
    assert _ensure_kisacevap_header(ok) == ok
    assert _ensure_kisacevap_header(plain) == plain


# --- partial-answer dürüst notu (Hedef-2: çok-konulu sessiz-eksiltme → şeffaf) ---

def _partial_state(base_state):
    claims = [
        {"text": "Destekli iddia cümlesi yeterince uzun olmalı burada", "cite_ids": ["m-TKHK-11"],
         "verified": False, "verify_score": 0.0, "verify_reason": ""},
        {"text": "Desteksiz uydurma iddia cümlesi de yeterince uzun olmalı", "cite_ids": [],
         "verified": False, "verify_score": 0.0, "verify_reason": ""},
    ]
    verified_claims = [
        {**claims[0], "verified": True, "verify_score": 0.9, "verify_reason": "ok"},
        {**claims[1], "verified": False, "verify_score": 0.1, "verify_reason": "Yetersiz kanıt"},
    ]
    return {
        **base_state,
        "draft_response": (
            "Destekli iddia cümlesi yeterince uzun olmalı burada. "
            "Desteksiz uydurma iddia cümlesi de yeterince uzun olmalı."
        ),
        "claims": claims, "verified_claims": verified_claims, "debate_verdict": "pass",
    }


@pytest.mark.asyncio
async def test_finalize_partial_note_when_dropped_and_enabled(base_state, monkeypatch):
    """PARTIAL_ANSWER_NOTE=1 + iddia düştü → grounded korunur, düşen DÜRÜSTÇE belirtilir."""
    monkeypatch.setenv("PARTIAL_ANSWER_NOTE", "1")
    out = await finalize_node(_partial_state(base_state))
    assert "Destekli iddia cümlesi" in out["response"]       # grounded korundu
    assert "Desteksiz uydurma iddia" not in out["response"]   # ungrounded düştü (halüsinasyon yok)
    assert "ayrı ayrı sorarsanız" in out["response"]          # dürüst partial-not eklendi


@pytest.mark.asyncio
async def test_finalize_no_partial_note_when_disabled(base_state, monkeypatch):
    """Flag kapalı (default) → not EKLENMEZ (baseline davranış korunur)."""
    monkeypatch.delenv("PARTIAL_ANSWER_NOTE", raising=False)
    out = await finalize_node(_partial_state(base_state))
    assert "Destekli iddia cümlesi" in out["response"]
    assert "ayrı ayrı sorarsanız" not in out["response"]
