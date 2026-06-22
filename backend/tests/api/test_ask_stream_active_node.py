"""SSE `node` event'inin `active_node` curated etiketi — "Ajan Akış Şeması" besler.

RED-LINE: _infer_active_node yalnız SABİT whitelist etiketi döndürür; iç TypedDict
anahtarı (list(state.keys())) ASLA sızmaz (ask.py:431-432 politikası)."""
from __future__ import annotations

from api.routes.ask import _ACTIVE_NODE_LABELS, _infer_active_node


def test_infer_active_node_each_stage():
    """State-alan varlığından en-ileri (en-spesifik) düğüm türetilir."""
    assert _infer_active_node({"triage_reasoning": "iş hukuku"}) == "triaj"
    assert _infer_active_node({"mevzuat_refs": [{"x": 1}]}) == "retrieval"
    assert _infer_active_node({"emsal_refs": [{"x": 1}]}) == "retrieval"
    assert _infer_active_node({"mevzuat_refs": [1], "draft_response": "..."}) == "draft"
    assert _infer_active_node({"draft_response": "...", "verified_claims": [{}]}) == "verify"
    # debate ETİKETİ debate_notes ile (init'te debate_verdict="pass" → SİNYAL DEĞİL, aksi halde
    # graph başından "debate" sızardı); debate_verdict tek başına "debate" döndürmemeli.
    assert _infer_active_node({"verified_claims": [{}], "debate_notes": "eleştiri"}) == "debate"
    assert _infer_active_node({"verified_claims": [{}], "debate_verdict": "pass"}) == "verify"
    assert _infer_active_node({"confidence_label": "Yüksek"}) == "finalize"
    assert _infer_active_node({"response": "cevap"}) == "finalize"
    assert _infer_active_node({"chat_response": "merhaba"}) == "chat"
    assert _infer_active_node({"clarify_response": True, "clarifying_questions": ["?"]}) == "clarifier"


def test_infer_active_node_empty_defaults_triaj():
    """Boş/erken state → triaj (graph başlangıcı)."""
    assert _infer_active_node({}) == "triaj"


def test_active_node_always_in_whitelist_never_leaks_state_keys():
    """RED-LINE: çıktı HER ZAMAN curated whitelist'te — iç state anahtarı ASLA dönmez.
    İç-şema isimleri (case_facts, triage_reasoning, retry_count...) state'te olsa bile
    bunlar active_node olarak SIZAMAZ."""
    leaky_state = {
        "case_facts": {"olay": "x"}, "triage_reasoning": "r", "retry_count": 2,
        "draft_response": "d", "verified_claims": [{}], "debate_verdict": "retry",
        "mevzuat_refs": [1, 2], "emsal_refs": [3], "domain": "isHukuku",
    }
    label = _infer_active_node(leaky_state)
    assert label in _ACTIVE_NODE_LABELS
    # hiçbir iç anahtar etiket olarak dönmesin
    for internal_key in leaky_state:
        if internal_key not in _ACTIVE_NODE_LABELS:
            assert label != internal_key
