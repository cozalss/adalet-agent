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
    # Güven şeffaflığı: legal path etiket + claim sayıları döndürür
    assert out["confidence_label"] in ("Yüksek güven", "Orta güven", "Dikkatli olun")
    assert out["n_verified_claims"] == 1
    assert out["n_total_claims"] == 1


@pytest.mark.asyncio
async def test_finalize_promotes_first_verified_sentence_as_bluf(base_state):
    """Orijinal 'Kısa cevap' (desteklenmeyen) düşünce, ilk DOĞRULANMIŞ cümle BLUF olur;
    eski boilerplate dolgu ASLA görünmez; halüsinasyon sızmaz."""
    claims = [
        {"text": "Kesinlikle haklısınız ve kazanırsınız", "cite_ids": [],
         "verified": False, "verify_score": 0.0, "verify_reason": ""},
        {"text": "Tüketici ayıplı malda sözleşmeden dönebilir", "cite_ids": ["m-TKHK-11"],
         "verified": False, "verify_score": 0.0, "verify_reason": ""},
    ]
    verified_claims = [
        {**claims[0], "verified": False},  # açıkça doğrulanmadı → düşer
        {**claims[1], "verified": True, "verify_score": 0.9, "verify_reason": "Fuzzy 0.90"},
    ]
    state = {
        **base_state,
        "draft_response": (
            "**Kısa cevap:** Kesinlikle haklısınız ve kazanırsınız.\n\n"
            "**Durumunuza uygulama:** Tüketici ayıplı malda sözleşmeden dönebilir [src: m-TKHK-11]."
        ),
        "claims": claims,
        "verified_claims": verified_claims,
        "debate_verdict": "pass",
    }

    out = await finalize_node(state)
    resp = out["response"]

    assert resp.lstrip().startswith("**Kısa cevap:** Tüketici ayıplı malda sözleşmeden dönebilir")
    assert "Kesinlikle haklısınız" not in resp           # halüsinasyon iddia düştü
    assert "yalnızca doğrulanmış kaynaklara dayanmaktadır" not in resp  # boilerplate yok
    assert "[src: m-TKHK-11]" in resp                     # grounding korundu


@pytest.mark.asyncio
async def test_finalize_reject_has_no_confidence_label(base_state):
    """Reddedilen yanıtta confidence_label None (legal analiz yok)."""
    state = {**base_state, "debate_verdict": "retry", "debate_notes": "Retry doldu"}
    out = await finalize_node(state)
    assert out.get("confidence_label") is None


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


def test_promote_bluf_extracts_first_verified_sentence_grounded():
    """BLUF düştüğünde gövdedeki ilk DOĞRULANMIŞ cümle 'Kısa cevap' olarak öne çekilir;
    [src:] etiketi korunur (grounding garanti — yeni iddia üretilmez). Başlık öneki SÖKÜLÜR."""
    from agents.nodes.finalize import _promote_first_verified_as_bluf
    body = "**Durumunuza uygulama:** Hakkınız var [src: m-TKHK-8].\n\n**Dayanak:** TKHK 8."
    out = _promote_first_verified_as_bluf(body)
    assert out.startswith("**Kısa cevap:** Hakkınız var [src: m-TKHK-8].")
    assert "**Dayanak:** TKHK 8." in out  # diğer bölümler korunur
    # Çift gösterim YOK: promote edilen cümle gövdede tekrar etmez; boş kalan başlık silinir
    assert out.count("Hakkınız var [src: m-TKHK-8].") == 1
    assert "**Durumunuza uygulama:**" not in out
    # Eski boilerplate dolgusu ASLA görünmez
    assert "yalnızca doğrulanmış kaynaklara dayanmaktadır" not in out


def test_promote_bluf_keeps_remaining_sentences_in_section():
    """İlk bölümde birden çok cümle varsa, ilki BLUF olur; kalanlar başlığı altında kalır."""
    from agents.nodes.finalize import _promote_first_verified_as_bluf
    body = "**Durumunuza uygulama:** İlk cümle [src: a]. İkinci cümle [src: b].\n\n**Dayanak:** X [src: c]."
    out = _promote_first_verified_as_bluf(body)
    assert out.startswith("**Kısa cevap:** İlk cümle [src: a].")
    assert "**Durumunuza uygulama:**" in out          # başlık korunur (içeriği kaldı)
    assert "İkinci cümle [src: b]." in out
    assert out.count("İlk cümle [src: a].") == 1       # çift yok


def test_promote_bluf_preserves_downstream_header_with_next_line_content():
    """HIGH regresyon: gövde İLERİSİNDEKİ 'başlık + sonraki satırda içerik' başlığı SİLİNMEZ
    (leading-anchored orphan yalnız baştaki boş başlığı temizler)."""
    from agents.nodes.finalize import _promote_first_verified_as_bluf
    body = "**Durum:** Hakkınız var [src: a].\n\n**Dayanak:**\nMadde 8 uygulanır [src: b]."
    out = _promote_first_verified_as_bluf(body)
    assert out.startswith("**Kısa cevap:** Hakkınız var [src: a].")
    assert "**Dayanak:**" in out             # ilerideki başlık KORUNUR
    assert "Madde 8 uygulanır [src: b]." in out


def test_promote_bluf_noop_when_present_or_plain():
    """Zaten 'Kısa cevap' varsa VEYA düz metin ise dokunma (çift-başlık/bozma yok)."""
    from agents.nodes.finalize import _promote_first_verified_as_bluf
    ok = "**Kısa cevap:** Hakkınız var."
    plain = "Hakkınız var, dava açabilirsiniz."
    assert _promote_first_verified_as_bluf(ok) == ok
    assert _promote_first_verified_as_bluf(plain) == plain


def test_promote_bluf_noop_when_only_headers():
    """Salt-başlık gövdesi (içerik cümlesi yok) → boilerplate EKLEME, çökme yok."""
    from agents.nodes.finalize import _promote_first_verified_as_bluf
    body = "**Başlık:**\n\n**Alt başlık:**"
    assert _promote_first_verified_as_bluf(body) == body


def test_first_content_sentence_only_promotes_src_anchored():
    """KAYNAĞA-BAĞLILIK garantisi: yalnız [src:] taşıyan cümle döner; salt-başlık atlanır,
    başlık öneki sökülür, [src:]'siz framing/çıkarım cümlesi PROMOTE EDİLMEZ (CRITICAL)."""
    from agents.nodes.finalize import _first_content_sentence
    assert _first_content_sentence("**A:**\n\n**B:**") is None
    assert _first_content_sentence("**Başlık:**\n\nGerçek cümle [src: x].") == "Gerçek cümle [src: x]."
    assert _first_content_sentence("**Başlık:** Inline cümle [src: z].") == "Inline cümle [src: z]."
    # CRITICAL: [src:]'siz cümle (dayanaksız çıkarım) BLUF'a çıkmaz
    assert _first_content_sentence("**Durum:** Bu durumda hakkınız yoktur.") is None
    # [src:]'siz framing önce gelse bile, ilk KAYNAKLI cümle seçilir
    two = "**Durum:** Genel bir değerlendirme. Asıl kural budur [src: m-X-1]."
    assert _first_content_sentence(two) == "Asıl kural budur [src: m-X-1]."


def test_first_content_sentence_merges_ordinal_within_section_not_across():
    """Sıra/madde-no fragmanı ('342.') bölüm İÇİNDE birleştirilir; yeni başlıkta sıfırlanır."""
    from agents.nodes.finalize import _first_content_sentence
    frag = "**Dayanak:** TBK'nın 342. maddesi güvenceyi sınırlar [src: m-TBK-342]."
    assert _first_content_sentence(frag) == "TBK'nın 342. maddesi güvenceyi sınırlar [src: m-TBK-342]."
    # Bölüm sınırını AŞMAZ: "342." fragmanı + sonraki BÖLÜM → birleşik uydurma cümle YOK
    cross = "**Dayanak:** TBK 342.\n\n**Başka:** Bambaşka bir konu [src: m-Y-2]."
    assert _first_content_sentence(cross) == "Bambaşka bir konu [src: m-Y-2]."


def test_confidence_label_thresholds():
    """Float skor → Türkçe etiket; eşikler (0.45 / 0.70) sınır değerlerinde doğru."""
    from agents.nodes.finalize import _confidence_label
    assert _confidence_label(0.0) == "Dikkatli olun"
    assert _confidence_label(0.449) == "Dikkatli olun"
    assert _confidence_label(0.45) == "Orta güven"
    assert _confidence_label(0.699) == "Orta güven"
    assert _confidence_label(0.70) == "Yüksek güven"
    assert _confidence_label(1.0) == "Yüksek güven"


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


def test_format_citations_only_from_shown_text():
    """ECC MEDIUM-3: kaynak listesi GÖSTERİLEN metinden — düşen cümlenin kaynağı listelenmez."""
    state = {
        "mevzuat_refs": [
            {"source_id": "m-A", "doc_type": "law", "title": "Kanun-Alfa", "url": ""},
            {"source_id": "m-B", "doc_type": "law", "title": "Kanun-Beta", "url": ""},
        ],
        "emsal_refs": [],
        "draft_response": "Hepsi. [src: m-A] [src: m-B]",
    }
    # Filtrelenmiş metin yalnız m-A içeriyor → yalnız Alfa listelenir (m-B düştü).
    out = _format_citations(state, "Gösterilen tek cümle. [src: m-A]")
    assert "Alfa" in out and "Beta" not in out


# --- proaktif next-step teklifi (keyword-only, hukuki iddia YOK) ---

def test_next_step_offer_keyword_match_per_domain():
    """Domain + gövdede anahtar eşleşince ilgili teklif döner; format doğru."""
    from agents.nodes.finalize import _next_step_offer
    out = _next_step_offer("kira", "Ev sahibi depozito iadesini reddediyor.", dilekce_shown=False)
    assert out.startswith("\n\n💡 *") and out.rstrip().endswith("*")
    assert "Depozito iadesi" in out
    assert "Kıdem" in _next_step_offer("isHukuku", "kıdem tazminatı hakkı", dilekce_shown=False)


def test_next_step_offer_suppressed_and_irrelevant_cases():
    """dilekçe linki varsa, domain bilinmiyorsa veya anahtar eşleşmiyorsa → '' (gürültü yok)."""
    from agents.nodes.finalize import _next_step_offer
    assert _next_step_offer("kira", "depozito", dilekce_shown=True) == ""        # dilekçe zaten var
    assert _next_step_offer("unknown", "depozito", dilekce_shown=False) == ""    # domain yok
    assert _next_step_offer("kira", "genel bir bilgi metni", dilekce_shown=False) == ""  # anahtar yok


def test_next_step_offer_turkish_capital_i_matches_and_no_legal_claim():
    """Türkçe İ-başlangıçlı kelime eşleşir (_tr_lower; düz .lower() bozardı); teklif
    metni madde-no/[src:] İÇERMEZ (kırmızı-çizgi)."""
    from agents.nodes.finalize import _next_step_offer
    # 'İşe iade' cümle başında İ ile → _tr_lower olmadan 'işe iade' anahtarı KAÇARDI
    out = _next_step_offer("isHukuku", "İşe iade davası açabilirsiniz.", dilekce_shown=False)
    assert out != "" and "İşe iade" in out
    assert "[src:" not in out and "madde" not in out.lower()


def test_next_step_offer_suppressed_on_negation():
    """Cevap hakkı REDDEDİYORSA (anahtar yakınında olumsuzluk) teklif sunulmaz (HIGH)."""
    from agents.nodes.finalize import _next_step_offer
    assert _next_step_offer("kira", "Bu durumda tahliye edilmesi mümkün değildir.", dilekce_shown=False) == ""
    assert _next_step_offer("tuketici", "Bu ürün için iade hakkınız bulunmamaktadır.", dilekce_shown=False) == ""
    assert _next_step_offer("idari", "İtiraz süresi dolmuştur, başvuru yapılamaz.", dilekce_shown=False) == ""
    # Pozitif bağlamda aynı anahtar → teklif sunulur (olumsuzluk yok)
    assert _next_step_offer("kira", "Tahliye için dava açabilirsiniz.", dilekce_shown=False) != ""


def test_next_step_offer_no_false_positive_on_zaman_cezaevi():
    """Sıkılaştırılmış anahtarlar: 'zam'→'zaman', 'ceza'→'cezaevi' YANLIŞ tetiklemez (MEDIUM)."""
    from agents.nodes.finalize import _next_step_offer
    assert _next_step_offer("kira", "Zamanaşımı süresi beş yıldır.", dilekce_shown=False) == ""
    assert _next_step_offer("trafik", "Cezaevi koşulları ayrı bir konudur.", dilekce_shown=False) == ""


@pytest.mark.asyncio
async def test_finalize_legal_answer_includes_offer_before_sources(base_state):
    """Legal yanıtta teklif Kaynaklar ayıracından ÖNCE; disclaimer en sonda kalır."""
    claims = [{"text": "Tüketici ayıplı malda sözleşmeden dönebilir", "cite_ids": ["m-TKHK-11"],
               "verified": False, "verify_score": 0.0, "verify_reason": ""}]
    verified_claims = [{**claims[0], "verified": True, "verify_score": 0.9, "verify_reason": "Fuzzy"}]
    state = {
        **base_state, "domain": "tuketici",
        "draft_response": "Ayıplı malda tüketici sözleşmeden dönebilir [src: m-TKHK-11].",
        "claims": claims, "verified_claims": verified_claims, "debate_verdict": "pass",
    }
    out = await finalize_node(state)
    resp = out["response"]
    assert "💡" in resp
    assert resp.index("💡") < resp.index("**Kaynaklar:**")  # teklif kaynaklardan önce
    assert resp.rstrip().endswith(out["disclaimers"][0].rstrip()[-20:]) or "tavsiye değildir" in resp


@pytest.mark.asyncio
async def test_finalize_no_offer_on_smalltalk(base_state):
    """Sohbet (smalltalk) yanıtında teklif YOK (yalnız legal-answer path)."""
    state = {**base_state, "smalltalk_response": "Merhaba!", "response_intent": "smalltalk"}
    out = await finalize_node(state)
    assert "💡" not in out["response"]
