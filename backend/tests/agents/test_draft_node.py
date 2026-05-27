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


def test_format_facts_empty_returns_empty_string():
    import agents.nodes.draft as draft_mod
    assert draft_mod._format_facts_for_prompt({}) == ""


def test_format_facts_renders_labels():
    import agents.nodes.draft as draft_mod
    out = draft_mod._format_facts_for_prompt({"sure": "3 ay", "olay": "fesih"})
    assert "Süre: 3 ay" in out
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
