"""Guided-decoding citation-whitelist (2.2) — birim testleri.

claim-extraction LLM çağrısında cite_id'i known_ids ENUM'una GBNF ile kısıtlar
(uydurma cite decode-seviyesinde üretilemez). Opt-in (GUIDED_CITE_ENABLED, default 0);
grammar destekleyen LLM'de etkin, MockLLM yok sayar → testler etkilenmez.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.nodes.draft import _extract_claims_llm, build_claims_schema
from agents.state import Citation

_REFS = [
    Citation(source_id="m-TKHK-11", doc_type="law", title="TKHK Madde 11",
             snippet="Tüketici ayıplı malda...", url="", score=0.9),
    Citation(source_id="m-IK-32", doc_type="law", title="İş Kanunu Madde 32",
             snippet="İşveren ücreti...", url="", score=0.8),
]
_CLAIMS_JSON = (
    '{"claims": [{"text": "Tüketici ayıplı malda iade hakkına sahiptir.", '
    '"cite_ids": ["m-TKHK-11"]}]}'
)


class _RecordingLLM:
    """json_schema kwarg'ını kaydeder; geçerli claims JSON döner."""

    def __init__(self) -> None:
        self.received_schema: object = "UNSET"

    async def chat(self, messages, *, temperature=0.1, max_tokens=1024,
                   json_mode=False, json_schema=None):
        self.received_schema = json_schema
        return SimpleNamespace(content=_CLAIMS_JSON, tokens_out=10)


def test_build_claims_schema_enum_sorted():
    schema = build_claims_schema(["m-IK-32", "m-TKHK-11"])
    enum = schema["properties"]["claims"]["items"]["properties"]["cite_ids"]["items"]["enum"]
    assert enum == ["m-IK-32", "m-TKHK-11"]  # sorted
    assert schema["required"] == ["claims"]


@pytest.mark.asyncio
async def test_guided_off_passes_no_schema(monkeypatch):
    """Default (kapalı): json_schema=None → baseline json_mode davranışı."""
    monkeypatch.delenv("GUIDED_CITE_ENABLED", raising=False)
    llm = _RecordingLLM()
    claims = await _extract_claims_llm("Bir taslak metni.", _REFS, llm)
    assert llm.received_schema is None
    assert len(claims) == 1  # claim çıkarımı yine çalışır


@pytest.mark.asyncio
async def test_guided_on_passes_enum_schema(monkeypatch):
    """Açık + refs var: cite_ids enum'lu schema geçilir (GBNF kısıtı)."""
    monkeypatch.setenv("GUIDED_CITE_ENABLED", "1")
    llm = _RecordingLLM()
    await _extract_claims_llm("Bir taslak metni.", _REFS, llm)
    assert isinstance(llm.received_schema, dict)
    enum = (llm.received_schema["properties"]["claims"]["items"]
            ["properties"]["cite_ids"]["items"]["enum"])
    assert set(enum) == {"m-TKHK-11", "m-IK-32"}


@pytest.mark.asyncio
async def test_guided_on_no_refs_no_schema(monkeypatch):
    """Açık ama refs YOK → enum kurulamaz → schema None (baseline, geçersiz grammar önlenir)."""
    monkeypatch.setenv("GUIDED_CITE_ENABLED", "1")
    llm = _RecordingLLM()
    await _extract_claims_llm("Bir taslak metni.", [], llm)
    assert llm.received_schema is None
