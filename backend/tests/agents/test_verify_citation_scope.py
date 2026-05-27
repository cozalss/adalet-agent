"""Verify Step-4 tightening — claim'in atıf yaptığı madde no'ya kanıt daraltma.

Açık (bug): LLM bir maddenin içeriğini başka maddeye atfederse (garbled m.31),
doğrulama yanlış snippet'le gevşek token örtüşmesi üzerinden geçebiliyordu.
Düzeltme: claim "Madde X" diyorsa kanıt X'in kaynağına daraltılır; X corpus'ta
yoksa grounding 0.0 (uydurma atıf).
"""

from __future__ import annotations

from agents import verifier_layers as vl
from agents.state import Citation, Claim


def _ref(source_id: str, title: str, snippet: str) -> Citation:
    return Citation(
        source_id=source_id, doc_type="law", title=title,
        snippet=snippet, url="https://mevzuat/x", score=0.9,
    )


def _claim(text: str, cite_ids: list[str] | None = None) -> Claim:
    return Claim(
        text=text, cite_ids=cite_ids or [], verified=False,
        verify_score=0.0, verify_reason="",
    )


# --- _stated_madde_numbers ---

def test_stated_madde_numbers_extracts():
    assert vl._stated_madde_numbers("İş Kanunu Madde 17 ve m.18 uyarınca") == {17, 18}


def test_stated_madde_numbers_empty_when_none():
    assert vl._stated_madde_numbers("işçi ihbar tazminatı alabilir") == set()


# --- _ref_madde_no ---

def test_ref_madde_no_from_source_id():
    assert vl._ref_madde_no(_ref("m-IK-31", "IK Madde 31", "x")) == 31


def test_ref_madde_no_from_title_when_sid_opaque():
    assert vl._ref_madde_no(_ref("uuid-abc", "EIK Madde 14", "x")) == 14


# --- _scope_refs_to_claim_madde ---

def test_scope_no_stated_madde_returns_all():
    refs = [_ref("m-IK-17", "IK Madde 17", "ihbar")]
    scoped, missing = vl._scope_refs_to_claim_madde("işçi hakları", refs)
    assert scoped == refs
    assert missing is False


def test_scope_narrows_to_stated_madde():
    refs = [
        _ref("m-IK-17", "IK Madde 17", "ihbar bildirim süresi"),
        _ref("m-IK-31", "IK Madde 31", "askerlik askı"),
    ]
    scoped, missing = vl._scope_refs_to_claim_madde("Madde 31 uyarınca ...", refs)
    assert [r["source_id"] for r in scoped] == ["m-IK-31"]
    assert missing is False


def test_scope_stated_but_missing_flags_true():
    refs = [_ref("m-IK-17", "IK Madde 17", "ihbar")]
    _scoped, missing = vl._scope_refs_to_claim_madde("Madde 999 uyarınca ...", refs)
    assert missing is True


# --- layer2_fuzzy ---

def test_layer2_scopes_to_cited_madde_not_best_match():
    """Garbled m.31 iddiası: içerik ihbar (m.17) gibi ama madde 31 deniyor.
    Daraltma kanıtı m.31'e bağlar — m.17 snippet'iyle kaçak eşleşme olmaz."""
    refs = [
        _ref("m-IK-17", "IK Madde 17",
             "İş sözleşmesini fesheden taraf ihbar bildirim süresine uymak zorundadır"),
        _ref("m-IK-31", "IK Madde 31",
             "Askerlik veya kanundan doğan çalışma nedeniyle iş sözleşmesi askıda kalır"),
    ]
    claim = _claim("İş Kanunu Madde 31 uyarınca işveren ihbar bildirim süresine uyar")
    _score, _title, best_idx = vl.layer2_fuzzy(claim, refs)
    # Daraltma → kanıt m.31 (index 1), yanlış m.17 (index 0) DEĞİL
    assert best_idx == 1


def test_layer2_missing_cited_madde_returns_zero():
    refs = [_ref("m-IK-17", "IK Madde 17", "ihbar bildirim süresi")]
    claim = _claim("Madde 999 uyarınca tüketici 5 kat tazminat alır")
    score, msg, idx = vl.layer2_fuzzy(claim, refs)
    assert score == 0.0
    assert idx == -1
    assert "kaynakta yok" in msg


def test_layer2_no_madde_in_claim_uses_all_refs():
    """Madde no söylemeyen claim eski davranışla tüm refs'e karşı eşleşir."""
    refs = [_ref("m-TKHK-11", "TKHK Madde 11",
                 "Tüketici ayıplı malda sözleşmeden dönebilir")]
    claim = _claim("Tüketici ayıplı malda sözleşmeden dönme hakkına sahiptir")
    score, _msg, idx = vl.layer2_fuzzy(claim, refs)
    assert idx == 0
    assert score > 0.5


# --- pick_evidence ---

def test_pick_evidence_scopes_to_stated_madde():
    refs = [
        _ref("m-IK-17", "IK Madde 17", "ihbar bildirim süresi metni"),
        _ref("m-IK-31", "IK Madde 31", "askerlik askı metni"),
    ]
    ev = vl.pick_evidence(_claim("Madde 31 hakkında"), refs)
    assert "askerlik" in ev
    assert "ihbar" not in ev


def test_pick_evidence_missing_madde_returns_empty():
    refs = [_ref("m-IK-17", "IK Madde 17", "ihbar")]
    assert vl.pick_evidence(_claim("Madde 999 hakkında"), refs) == ""
