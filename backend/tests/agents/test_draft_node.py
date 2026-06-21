"""draft_node — system prompt (SIFIR HALÜSİNASYON) + temel davranış (W17).

Mock LLM prompt içeriğini yok saydığı için davranış testi yapamayız; bunun
yerine system prompt'un fabrication-ban içerdiğini ve chat çağrısına gerçekten
geçtiğini (wiring) doğrularız — zayıf prompt'a regresyonu önler.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.state import Citation


class _CapturingLLM:
    """chat()'e geçen mesajları yakalar; sabit cevap döner."""

    def __init__(self) -> None:
        self.messages = None

    async def chat(self, *, messages, **_kwargs):
        self.messages = messages
        return SimpleNamespace(content="Tüketici hakkı vardır [src: m-TKHK-11]", tokens_out=8)


def _ref() -> Citation:
    return Citation(
        source_id="m-TKHK-11",
        doc_type="law",
        title="TKHK Madde 11",
        snippet="Tüketici ayıplı malda sözleşmeden dönebilir.",
        url="https://mevzuat.gov.tr/madde/TKHK/11",
        score=0.9,
    )


@pytest.mark.asyncio
async def test_draft_system_prompt_forbids_fabrication(monkeypatch):
    import agents.nodes.draft as draft_mod

    cap = _CapturingLLM()
    monkeypatch.setattr(draft_mod, "get_llm", lambda: cap)

    state = {
        "question": "Ayıplı malda tüketici hakkı nedir?",
        "mevzuat_refs": [_ref()],
        "emsal_refs": [],
    }
    out = await draft_mod.draft_node(state)
    assert out["draft_response"]

    sys_msg = next(m for m in cap.messages if m.role == "system")
    low = sys_msg.content.lower()
    # Fabrication-ban + kaynak-kısıtı açıkça olmalı
    assert "uydurma" in low
    assert "kaynak" in low
    assert "avukat" in low


@pytest.mark.asyncio
async def test_draft_prompt_has_eligibility_steps(monkeypatch):
    """Eşik-kontrolü düşünme adımları (Step-3) user prompt'a geçmeli — eksik
    hakkı 'var' gibi sunma regresyonunu önler."""
    import agents.nodes.draft as draft_mod

    cap = _CapturingLLM()
    monkeypatch.setattr(draft_mod, "get_llm", lambda: cap)
    await draft_mod.draft_node({
        "question": "işten atıldım haklarım?",
        "mevzuat_refs": [_ref()],
        "emsal_refs": [],
    })
    user_msg = next(m for m in cap.messages if m.role == "user")
    low = user_msg.content.lower()
    assert "eşik" in low or "şart" in low       # eşik/şart kontrolü
    # eksik şartlı hakkı reddet talimatı: "doğmaz"/"doğmadığını"/"hak yok" formları
    assert "doğma" in low or "hak yok" in low or "hakkınız yok" in low


@pytest.mark.asyncio
async def test_draft_injects_case_facts(monkeypatch):
    """Triaj olguları varsa draft prompt'una somut hint olarak gömülür."""
    import agents.nodes.draft as draft_mod

    cap = _CapturingLLM()
    monkeypatch.setattr(draft_mod, "get_llm", lambda: cap)
    await draft_mod.draft_node({
        "question": "işten atıldım",
        "mevzuat_refs": [_ref()],
        "emsal_refs": [],
        "case_facts": {"sure": "3 ay", "olay": "işten çıkarıldı"},
    })
    user_msg = next(m for m in cap.messages if m.role == "user")
    assert "3 ay" in user_msg.content
    assert "işten çıkarıldı" in user_msg.content


@pytest.mark.asyncio
async def test_draft_no_facts_leaves_placeholder_clean(monkeypatch):
    """case_facts yoksa {olgular_blogu} boşa indirgenir — ham placeholder sızmaz."""
    import agents.nodes.draft as draft_mod

    cap = _CapturingLLM()
    monkeypatch.setattr(draft_mod, "get_llm", lambda: cap)
    await draft_mod.draft_node({
        "question": "soru", "mevzuat_refs": [_ref()], "emsal_refs": [],
    })
    user_msg = next(m for m in cap.messages if m.role == "user")
    assert "{olgular_blogu}" not in user_msg.content


def test_select_draft_model_off_returns_none(monkeypatch):
    """LLM_TIER_ROUTING kapalı (default) → her zaman None (varsayılan model, sıfır değişiklik)."""
    import agents.nodes.draft as draft_mod
    monkeypatch.delenv("LLM_TIER_ROUTING", raising=False)
    assert draft_mod._select_draft_model("x" * 200, {"a": "1", "b": "2"}, "icra") is None


def test_select_draft_model_on_routes_complex_and_high_risk(monkeypatch):
    """Flag açık → karmaşık (≥2 olgu/uzun) VEYA yüksek-riskli → güçlü model; basit → None."""
    import agents.nodes.draft as draft_mod
    monkeypatch.setenv("LLM_TIER_ROUTING", "1")
    monkeypatch.setenv("OPENAI_LLM_MODEL_COMPLEX", "gpt-4o")
    # basit + düşük-risk → varsayılan (None)
    assert draft_mod._select_draft_model("kıdem nedir", {}, "is") is None
    # karmaşık (≥2 olgu) → güçlü
    assert draft_mod._select_draft_model("durumum", {"a": "1", "b": "2"}, "is") == "gpt-4o"
    # yüksek-riskli (icra domain) basit soru olsa bile → güçlü
    assert draft_mod._select_draft_model("borcum var", {}, "icra") == "gpt-4o"


def test_format_facts_empty_returns_empty_string():
    import agents.nodes.draft as draft_mod
    assert draft_mod._format_facts_for_prompt({}) == ""


def test_format_facts_renders_labels():
    import agents.nodes.draft as draft_mod
    out = draft_mod._format_facts_for_prompt({"sure": "3 ay", "olay": "fesih"})
    assert "Kullanıcının belirttiği süre (kanuni süre değildir): 3 ay" in out
    assert "Olay: fesih" in out


def test_format_eligibility_empty_returns_empty():
    import agents.nodes.draft as draft_mod
    assert draft_mod._format_eligibility_for_prompt([]) == ""


def test_format_eligibility_renders_verdict_labels():
    import agents.nodes.draft as draft_mod
    out = draft_mod._format_eligibility_for_prompt([
        {"madde": "m-EIK-14", "hak": "kıdem", "kosul": "1 yıl",
         "saglaniyor": "hayir", "gerekce": "3 ay < 1 yıl"},
        {"madde": "m-IK-17", "hak": "ihbar", "kosul": "-",
         "saglaniyor": "evet", "gerekce": "her kıdemde"},
    ])
    assert "HAK YOK" in out and "kıdem" in out
    assert "HAK VAR" in out and "ihbar" in out


@pytest.mark.asyncio
async def test_draft_injects_eligibility(monkeypatch):
    """Uygunluk kararları varsa draft prompt'una önceden-hesaplanmış blok girer."""
    import agents.nodes.draft as draft_mod

    cap = _CapturingLLM()
    monkeypatch.setattr(draft_mod, "get_llm", lambda: cap)
    await draft_mod.draft_node({
        "question": "işten atıldım",
        "mevzuat_refs": [_ref()],
        "emsal_refs": [],
        "eligibility": [
            {"madde": "m-EIK-14", "hak": "kıdem", "kosul": "1 yıl",
             "saglaniyor": "hayir", "gerekce": "3 ay < 1 yıl"},
        ],
    })
    user_msg = next(m for m in cap.messages if m.role == "user")
    assert "UYGUNLUK DEĞERLENDİRMESİ" in user_msg.content
    assert "HAK YOK" in user_msg.content


def test_format_refs_caps_count_and_snippet():
    """Context-taşma fix: çok/uzun ref draft prompt'unu şişirip n_ctx'i aşmasın."""
    import agents.nodes.draft as draft_mod

    refs = [
        Citation(
            source_id=f"m-TBK-{i}", doc_type="law", title=f"TBK Madde {i}",
            snippet="çok uzun madde metni " * 100,  # ~2000 char
            url="https://mevzuat/x", score=0.9,
        )
        for i in range(15)
    ]
    out = draft_mod._format_refs_for_prompt(refs)
    # En fazla _MAX_DRAFT_REFS ref + her snippet _DRAFT_SNIPPET_CHARS ile sınırlı
    assert out.count("[m-TBK-") <= draft_mod._MAX_DRAFT_REFS
    # Hiçbir tek snippet 450+pay'ı aşmamalı (kabaca: toplam budget sınırı)
    assert len(out) <= int(draft_mod.LLM_CONTEXT_BUDGET * draft_mod._CHARS_PER_TOKEN_TR) + 800


def test_clean_draft_removes_model_source_block_and_incomplete_tail():
    import agents.nodes.draft as draft_mod

    raw = (
        "**Kısa cevap:** Depozito istenebilir [src: m-TBK-372].\n\n"
        "**Ne yapmalı:** Yazılı talep gönderin [src: m-TBK-372]. Yarım kalan cümle [src: m-TBK-37"
        "\n\n---\n**Kaynaklar:**\n- modelin yazdığı gereksiz liste"
    )

    out = draft_mod._clean_draft_response(raw)

    assert "Kaynaklar" not in out
    assert "[src: m-TBK-37" not in out.replace("[src: m-TBK-372]", "")
    assert out.endswith("[src: m-TBK-372].")


def test_prioritize_refs_keeps_one_case_when_laws_exist():
    import agents.nodes.draft as draft_mod

    refs = [
        Citation(source_id=f"m-IK-{i}", doc_type="law", title=f"IK Madde {i}",
                 snippet="iş hukuku", url="https://mevzuat/x", score=0.5)
        for i in range(1, 6)
    ]
    refs.append(Citation(
        source_id="y-9hd-1", doc_type="case", title="Yargıtay 9.HD",
        snippet="emsal karar", url="", score=0.4,
    ))

    out = draft_mod._prioritize_refs_for_prompt(refs, "kıdem ihbar tazminatı")

    assert any(r["doc_type"] == "case" for r in out[:draft_mod._MAX_DRAFT_REFS])


def test_extract_claims_splits_structured_sections(sample_citations):
    import agents.nodes.draft as draft_mod

    text = (
        "**Kısa cevap:** Hak isteyebilirsiniz [src: m-TKHK-11].\n\n"
        "**Dayanak:** TKHK Madde 11 seçimlik hakları düzenler [src: m-TKHK-11].\n\n"
        "**Ne yapmalı:** Satıcıya yazılı başvurun [src: m-TKHK-11]."
    )

    claims = draft_mod._extract_claims(text, sample_citations)

    assert len(claims) == 3
    assert all("\n\n" not in c["text"] for c in claims)


def test_backfill_missing_source_tags_uses_relevant_existing_ref():
    import agents.nodes.draft as draft_mod

    refs = [
        Citation(source_id="m-TBK-342", doc_type="law", title="TBK Madde 342",
                 snippet="güvence bedeli depozito", url="https://mevzuat/342", score=0.5),
        Citation(source_id="m-TBK-315", doc_type="law", title="TBK Madde 315",
                 snippet="temerrüt", url="https://mevzuat/315", score=0.9),
    ]
    text = (
        "**Kısa cevap:** Depozito iade edilmelidir.\n\n"
        "**Ne yapmalı:** Ev sahibine yazılı talep gönderin."
    )

    out = draft_mod._backfill_missing_source_tags(text, refs, "depozito iade edilmiyor")

    assert "Depozito iade edilmelidir. [src: m-TBK-342]" in out
    assert "Ev sahibine yazılı talep gönderin. [src:" not in out


def test_prioritize_refs_prefers_tkhk_for_defective_goods_over_service_regulation():
    import agents.nodes.draft as draft_mod

    refs = [
        Citation(source_id="y-YON_SSH-c9", doc_type="law", title="YON_SSH Madde chunk-9",
                 snippet="servis süresi", url="https://mevzuat/ssh", score=0.95),
        Citation(source_id="m-TKHK-11", doc_type="law", title="TKHK Madde 11",
                 snippet="ayıplı malda tüketicinin seçimlik hakları", url="https://mevzuat/11", score=0.5),
        Citation(source_id="m-TKHK-8", doc_type="law", title="TKHK Madde 8",
                 snippet="ayıplı mal", url="https://mevzuat/8", score=0.5),
    ]

    out = draft_mod._prioritize_refs_for_prompt(
        refs,
        "İnternetten 10 gün önce telefon aldım, arızalı çıktı, iade veya değişim istiyorum.",
    )

    assert [r["source_id"] for r in out[:2]] == ["m-TKHK-11", "m-TKHK-8"]


def test_remove_unsafe_duration_inferences_without_eligibility():
    import agents.nodes.draft as draft_mod

    text = (
        "**Kısa cevap:** İade hakkınız olabilir [src: m-TKHK-11].\n\n"
        "**Durumuna uygulama:** Belirtilen süre geçtiği için bu şartı karşılamadınız. [src: m-TKHK-11]\n\n"
        "10 gün süresi geçerli değildir. [src: m-TKHK-11]\n\n"
        "**Ne yapmalı:** Satıcıya yazılı başvurun."
    )

    out = draft_mod._remove_unsafe_duration_inferences(text, {"sure": "10 gün"}, [])

    assert "şartı karşılamadınız" not in out
    assert "süresi geçerli değildir" not in out
    assert "İade hakkınız olabilir" in out
    assert "Satıcıya yazılı başvurun" in out


def test_keep_eligibility_denial_when_eligibility_supplied():
    """Saf uygunluk-reddi (deadline markeri YOK) — eligibility node karar verdiyse korunur."""
    import agents.nodes.draft as draft_mod

    text = "Çalışma süreniz yetersiz olduğundan bu şartı karşılamadınız. [src: m-X]"

    out = draft_mod._remove_unsafe_duration_inferences(
        text,
        {"sure": "6 ay"},
        [{"saglaniyor": "hayir", "madde": "m-X"}],
    )

    assert out == text


def test_remove_deadline_fabrication_even_with_eligibility():
    """KIRMIZI ÇİZGİ (denetim 2026-06-04): deadline-uydurma (kullanıcı süresini kanuni
    deadline'a çevirme) eligibility VARKEN BİLE silinir — deadline ≠ uygunluk-asgarisi,
    eligibility node bunu adjudike etmez. Eski 'eligibility varsa atla' deliği kapandı."""
    import agents.nodes.draft as draft_mod

    text = "Belirtilen 10 günlük süre geçtiği için itiraz hakkınız kalmadı. [src: m-X]"

    out = draft_mod._remove_unsafe_duration_inferences(
        text,
        {"sure": "10 gün"},
        [{"saglaniyor": "evet", "madde": "m-X"}],
    )

    assert "geçtiği için" not in out


def test_remove_deadline_fabrication_even_without_user_duration():
    """ECC review HIGH-1 (kanıtlanmış red-line gap): kullanıcı süre VERMESE de (facts boş)
    'süre geçti/geçtiği için hak yok' uydurması silinir — eski `if not facts.get('sure'): return`
    erken-çıkış deliği kapandı. Model facts-siz soruda da bu yanlış-çıkarımı uydurabilir."""
    import agents.nodes.draft as draft_mod

    text = (
        "**Kısa cevap:** Hakkınız olabilir. [src: m-X]\n\n"
        "Başvuru süresi geçtiği için itiraz hakkınız kalmadı. [src: m-X]"
    )
    out = draft_mod._remove_unsafe_duration_inferences(text, {}, [])

    assert "geçtiği için" not in out          # facts boş olsa da deadline-uydurma silindi
    assert "Hakkınız olabilir" in out         # güvenli içerik korundu


@pytest.mark.asyncio
async def test_draft_llm_failure_degrades_to_empty(monkeypatch):
    """LLM çağrısı çökerse (context taşması/OOM) graph çökmesin — boş draft + hata."""
    import agents.nodes.draft as draft_mod

    class _BoomLLM:
        async def chat(self, **_kwargs):
            raise RuntimeError("llama_decode returned -1")

    monkeypatch.setattr(draft_mod, "get_llm", lambda: _BoomLLM())
    out = await draft_mod.draft_node({
        "question": "soru", "mevzuat_refs": [_ref()], "emsal_refs": [],
    })
    assert out["draft_response"] == ""
    assert out["claims"] == []
    assert out["errors"] and "LLM" in out["errors"][0]


@pytest.mark.asyncio
async def test_draft_no_refs_returns_empty(monkeypatch):
    """Kaynak yoksa LLM çağrılmadan boş taslak + hata döner (mevcut sözleşme)."""
    import agents.nodes.draft as draft_mod

    called = {"chat": False}

    class _ShouldNotCall:
        async def chat(self, **_kwargs):
            called["chat"] = True
            return SimpleNamespace(content="x", tokens_out=0)

    monkeypatch.setattr(draft_mod, "get_llm", lambda: _ShouldNotCall())
    out = await draft_mod.draft_node(
        {"question": "soru", "mevzuat_refs": [], "emsal_refs": []},
    )
    assert out["draft_response"] == ""
    assert out["claims"] == []
    assert called["chat"] is False


def test_clean_draft_drops_truncated_trailing_section():
    """truncated=True: kesik son bölüm ('**Güven:** …8., 10. ve 11.') atılır, tam
    bölümler ('11.' numara-noktası tam cümle sanılmaz) korunur (gerçek-LLM 2026-06-04)."""
    import agents.nodes.draft as draft_mod

    raw = (
        "**Kısa cevap:** Ayıplı maldan dolayı iade hakkınız var. [src: m-TKHK-8]\n\n"
        "**Dikkat:** Süreyi kaçırmayın.\n\n"
        "**Güven:** Bu yanıt, TKHK'nın 8., 10. ve 11."
    )
    out = draft_mod._clean_draft_response(raw, truncated=True)
    assert "**Güven:**" not in out
    assert out.rstrip().endswith("Süreyi kaçırmayın.")


def test_clean_draft_keeps_complete_section_when_truncated_flag():
    """truncated=True ama son bölüm TAM ise düşürülmez (aşırı kırpma yok)."""
    import agents.nodes.draft as draft_mod

    raw = (
        "**Kısa cevap:** Hakkınız var. [src: m-TKHK-8]\n\n"
        "**Güven:** Bu yanıt TKHK 8. maddesine dayanır."
    )
    out = draft_mod._clean_draft_response(raw, truncated=True)
    assert "**Güven:**" in out
    assert out.rstrip().endswith("dayanır.")


def test_clean_history_turn_strips_citation_and_sources():
    """Asistan turundan [src:] etiketleri + Kaynaklar bloğu (ve sonrası disclaimer)
    ayıklanır → geçmiş sade gövde olur, model citation/disclaimer formatını taklit etmez."""
    import agents.nodes.draft as draft_mod

    raw = (
        "**Kısa cevap:** Depozito iade edilir. [src: m-TBK-342]\n\n"
        "---\n**Kaynaklar:**\n- [TBK 342](https://x)\n\n"
        "Bu yanıt hukuki tavsiye değildir, bilgilendirme amaçlıdır."
    )
    out = draft_mod._clean_history_turn(raw)
    assert "[src:" not in out
    assert "Kaynaklar" not in out
    assert "hukuki tavsiye değildir" not in out
    assert "Depozito iade edilir." in out


def test_format_history_cleans_assistant_keeps_user_and_limits():
    """Asistan turu temizlenir, kullanıcı turu ham kalır; kırpma TEMİZLİKTEN SONRA
    (gerçek içerik sınır içine girer) + yeni 5-tur/800-char limitleri."""
    import agents.nodes.draft as draft_mod

    assert draft_mod._MAX_HISTORY_TURNS == 5
    assert draft_mod._MAX_HISTORY_CHAR == 800

    history = [
        {"role": "user", "content": "kiramı ev sahibi artırdı"},
        {
            "role": "assistant",
            "content": (
                "**Kısa cevap:** Artış TÜFE ile sınırlıdır. [src: m-TBK-344]\n\n"
                "---\n**Kaynaklar:**\n- TBK 344\n\nBu yanıt hukuki tavsiye değildir."
            ),
        },
    ]
    out = draft_mod._format_history_for_prompt(history)
    assert "ÖNCEKİ KONUŞMA" in out
    assert "Kullanıcı: kiramı ev sahibi artırdı" in out
    # Asistan turu temizlenmiş: artık ne [src:] ne Kaynaklar ne disclaimer
    assert "[src:" not in out
    assert "Kaynaklar" not in out
    assert "hukuki tavsiye değildir" not in out
    assert "Artış TÜFE ile sınırlıdır." in out


# --- Quote-grounding flag (opt-in, Anthropic finding-3; default OFF = baseline) ---
def test_build_draft_system_baseline_omits_quote_grounding(monkeypatch):
    """Flag KAPALI (default) → quote-grounding kuralı YOK; birebir _DRAFT_SYSTEM (sıfır değişiklik)."""
    import agents.nodes.draft as draft_mod
    monkeypatch.delenv("DRAFT_QUOTE_GROUNDING", raising=False)
    sysprompt = draft_mod._build_draft_system()
    assert sysprompt == draft_mod._DRAFT_SYSTEM
    assert "KANIT-ÖNCE" not in sysprompt


def test_build_draft_system_appends_rule_when_flag_on(monkeypatch):
    """Flag AÇIK → kanıt-önce kuralı eklenir; mevcut MUTLAK KURALLAR korunur (üstüne eklenir)."""
    import agents.nodes.draft as draft_mod
    monkeypatch.setenv("DRAFT_QUOTE_GROUNDING", "1")
    sysprompt = draft_mod._build_draft_system()
    assert "KANIT-ÖNCE" in sysprompt
    assert sysprompt.startswith(draft_mod._DRAFT_SYSTEM)  # baseline kurallar bozulmadan kalır
    assert "Ayrı bir 'alıntı' bölümü YAZMA" in sysprompt  # çıktı formatı korunur uyarısı


@pytest.mark.asyncio
async def test_draft_node_injects_quote_grounding_when_enabled(monkeypatch):
    """Flag açıkken draft_node LLM'e geçen system mesajı kanıt-önce kuralını taşır."""
    import agents.nodes.draft as draft_mod
    monkeypatch.setenv("DRAFT_QUOTE_GROUNDING", "1")
    cap = _CapturingLLM()
    monkeypatch.setattr(draft_mod, "get_llm", lambda: cap)
    await draft_mod.draft_node({
        "question": "Ayıplı malda tüketici hakkı nedir?",
        "mevzuat_refs": [_ref()],
        "emsal_refs": [],
    })
    sys_msg = next(m for m in cap.messages if m.role == "system")
    assert "KANIT-ÖNCE" in sys_msg.content
