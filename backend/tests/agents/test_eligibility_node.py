"""Uygunluk node'u (Step-3b yapılandırılmış akıl yürütme) testleri.

Node retrieve edilen maddeleri kullanıcı olgularıyla eşik-karşılaştırıp
{madde, hak, kosul, saglaniyor, gerekce} JSON kararı üretir. Draft bunu render
eder. Eşikler yalnız madde metninden (uydurma yok).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agents.nodes import eligibility as elig_mod
from agents.state import Citation


def _law_ref(source_id: str, title: str, snippet: str) -> Citation:
    return Citation(
        source_id=source_id, doc_type="law", title=title,
        snippet=snippet, url="https://mevzuat/x", score=0.9,
    )


class _FakeLLM:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.messages = None

    async def chat(self, *, messages, **_kw):
        self.messages = messages
        return SimpleNamespace(content=json.dumps(self._payload, ensure_ascii=False))


def _enable(monkeypatch):
    monkeypatch.setattr(elig_mod, "ELIGIBILITY_ENABLED", True)


# --- _parse ---

def test_parse_valid_assessments():
    raw = json.dumps({"degerlendirmeler": [
        {"madde": "m-EIK-14", "hak": "kıdem", "kosul": "1 yıl",
         "saglaniyor": "hayir", "gerekce": "3 ay < 1 yıl"},
    ]}, ensure_ascii=False)
    out = elig_mod._parse(raw, {"m-EIK-14"})
    assert out[0]["saglaniyor"] == "hayir"
    assert out[0]["hak"] == "kıdem"


def test_parse_filters_invalid_verdict():
    raw = json.dumps({"degerlendirmeler": [
        {"madde": "m-IK-17", "hak": "ihbar", "saglaniyor": "MAYBE", "gerekce": ""},
        {"madde": "m-IK-18", "hak": "işe iade", "saglaniyor": "evet", "gerekce": "x"},
    ]})
    out = elig_mod._parse(raw, {"m-IK-17", "m-IK-18"})
    assert [a["saglaniyor"] for a in out] == ["evet"]


def test_parse_bad_json_returns_empty():
    assert elig_mod._parse("değil json {{", {"x"}) == []


# --- node davranışı ---

@pytest.mark.asyncio
async def test_node_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(elig_mod, "ELIGIBILITY_ENABLED", False)
    out = await elig_mod.eligibility_node({
        "domain": "isHukuku", "case_facts": {"sure": "3 ay"},
        "mevzuat_refs": [_law_ref("m-IK-17", "IK Madde 17", "ihbar")],
    })
    assert out == {}


@pytest.mark.asyncio
async def test_node_unknown_domain_returns_empty(monkeypatch):
    _enable(monkeypatch)
    out = await elig_mod.eligibility_node({"domain": "unknown"})
    assert out == {}


@pytest.mark.asyncio
async def test_node_no_facts_skips(monkeypatch):
    """Olgu yoksa eşik karşılaştırması anlamsız → boş (draft kendi idare eder)."""
    _enable(monkeypatch)
    out = await elig_mod.eligibility_node({
        "domain": "isHukuku", "case_facts": {},
        "mevzuat_refs": [_law_ref("m-IK-17", "IK Madde 17", "ihbar")],
    })
    assert out == {}


@pytest.mark.asyncio
async def test_node_no_law_refs_returns_empty(monkeypatch):
    _enable(monkeypatch)
    out = await elig_mod.eligibility_node({
        "domain": "isHukuku", "case_facts": {"sure": "3 ay"}, "mevzuat_refs": [],
    })
    assert out == {}


@pytest.mark.asyncio
async def test_node_happy_path_returns_assessments(monkeypatch):
    _enable(monkeypatch)
    fake = _FakeLLM({"degerlendirmeler": [
        {"madde": "m-EIK-14", "hak": "kıdem tazminatı", "kosul": "en az 1 yıl",
         "saglaniyor": "hayir", "gerekce": "3 ay < 1 yıl, şart dolmadı"},
        {"madde": "m-IK-17", "hak": "ihbar tazminatı", "kosul": "süre şartı yok",
         "saglaniyor": "evet", "gerekce": "her kıdemde bildirim hakkı"},
    ]})
    monkeypatch.setattr(elig_mod, "get_llm", lambda: fake)
    out = await elig_mod.eligibility_node({
        "domain": "isHukuku",
        "case_facts": {"sure": "3 ay", "olay": "işten çıkarıldı"},
        "mevzuat_refs": [
            _law_ref("m-EIK-14", "EIK Madde 14", "bir yıllık kıdem..."),
            _law_ref("m-IK-17", "IK Madde 17", "ihbar bildirim süreleri..."),
        ],
    })
    verdicts = {a["madde"]: a["saglaniyor"] for a in out["eligibility"]}
    assert verdicts == {"m-EIK-14": "hayir", "m-IK-17": "evet"}
    # Olgular system+user prompt'a gerçekten geçti mi?
    user_msg = next(m for m in fake.messages if m.role == "user")
    assert "3 ay" in user_msg.content


@pytest.mark.asyncio
async def test_node_llm_failure_degrades_to_empty(monkeypatch):
    _enable(monkeypatch)

    class _Boom:
        async def chat(self, **_kw):
            raise RuntimeError("llm çöktü")

    monkeypatch.setattr(elig_mod, "get_llm", lambda: _Boom())
    out = await elig_mod.eligibility_node({
        "domain": "isHukuku", "case_facts": {"sure": "3 ay"},
        "mevzuat_refs": [_law_ref("m-IK-17", "IK Madde 17", "ihbar")],
    })
    assert out == {}  # best-effort: çökerse draft kendi prompt'uyla devam eder
