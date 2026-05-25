"""CRAG (Corrective RAG) — confidence-based correction tests."""

from __future__ import annotations

import os

import pytest

os.environ["CRAG_ENABLED"] = "1"

from agents.nodes import crag as crag_mod
from agents.nodes.crag import _dedupe_by_id, _format_title, crag_node
from agents.state import Citation


@pytest.mark.asyncio
async def test_crag_disabled_returns_noop(monkeypatch, base_state):
    monkeypatch.setattr(crag_mod, "CRAG_ENABLED", False)
    out = await crag_node(base_state)
    assert out == {}


@pytest.mark.asyncio
async def test_crag_no_refs_returns_noop(monkeypatch, base_state):
    """Hiç ref yoksa correction atlanır."""
    monkeypatch.setattr(crag_mod, "CRAG_ENABLED", True)
    state = {**base_state, "mevzuat_refs": [], "emsal_refs": []}
    out = await crag_node(state)
    assert out == {}


@pytest.mark.asyncio
async def test_crag_high_confidence_passes_through(monkeypatch, base_state):
    """top_score >= THRESHOLD VE refs >= MIN_REFS → correction tetiklenmez."""
    monkeypatch.setattr(crag_mod, "CRAG_ENABLED", True)
    monkeypatch.setattr(crag_mod, "CRAG_CONFIDENCE_THRESHOLD", 0.30)
    monkeypatch.setattr(crag_mod, "CRAG_MIN_REFS", 2)
    # base_state'te mevzuat_refs en yüksek score 0.92, emsal 0.78 → toplam 3 ref
    out = await crag_node(base_state)
    assert out == {}


@pytest.mark.asyncio
async def test_crag_low_confidence_triggers_correction(monkeypatch, base_state):
    """top_score < THRESHOLD → multi-query + graph correction çağrılır."""
    monkeypatch.setattr(crag_mod, "CRAG_ENABLED", True)
    monkeypatch.setattr(crag_mod, "CRAG_CONFIDENCE_THRESHOLD", 0.99)  # her zaman düşük
    monkeypatch.setattr(crag_mod, "CRAG_MIN_REFS", 1)

    called: dict[str, bool] = {"mq": False, "graph": False}

    async def _fake_mq(state):
        called["mq"] = True
        new_law = Citation(
            source_id="m-NEW-1", doc_type="law", title="Yeni Madde",
            snippet="...", url="", score=0.7,
        )
        return [new_law], []

    async def _fake_graph(state, refs):
        called["graph"] = True
        return {"law": [], "case": []}

    monkeypatch.setattr(crag_mod, "_multi_query_correct", _fake_mq)
    monkeypatch.setattr(crag_mod, "_graph_expand_correct", _fake_graph)

    out = await crag_node(base_state)
    assert called["mq"] is True
    assert called["graph"] is True
    # Yeni law eklenmiş olmalı
    assert "mevzuat_refs" in out
    assert any(r["source_id"] == "m-NEW-1" for r in out["mevzuat_refs"])


@pytest.mark.asyncio
async def test_crag_dedupes_existing_refs(monkeypatch, base_state):
    """Multi-query mevcut id'leri tekrar getirirse dedupe etmeli."""
    monkeypatch.setattr(crag_mod, "CRAG_ENABLED", True)
    monkeypatch.setattr(crag_mod, "CRAG_CONFIDENCE_THRESHOLD", 0.99)
    monkeypatch.setattr(crag_mod, "CRAG_MIN_REFS", 99)

    async def _fake_mq(state):
        # base_state'teki m-TKHK-11 ile aynı id → dedupe edilmeli
        dup = Citation(
            source_id="m-TKHK-11", doc_type="law", title="TKHK 11 dup",
            snippet="...", url="", score=0.7,
        )
        new = Citation(
            source_id="m-FRESH", doc_type="law", title="Fresh", snippet="...",
            url="", score=0.7,
        )
        return [dup, new], []

    async def _fake_graph(state, refs):
        return {"law": [], "case": []}

    monkeypatch.setattr(crag_mod, "_multi_query_correct", _fake_mq)
    monkeypatch.setattr(crag_mod, "_graph_expand_correct", _fake_graph)

    out = await crag_node(base_state)
    # Yeni eklenenler: sadece m-FRESH (dup atılır)
    if "mevzuat_refs" in out:
        ids = {r["source_id"] for r in out["mevzuat_refs"]}
        assert "m-FRESH" in ids
        assert "m-TKHK-11" not in ids  # dedupe: zaten state'te


def test_dedupe_by_id_preserves_first():
    refs = [
        Citation(source_id="a", doc_type="law", title="A", snippet="", url="", score=0.9),
        Citation(source_id="a", doc_type="law", title="A-dup", snippet="", url="", score=0.5),
        Citation(source_id="b", doc_type="case", title="B", snippet="", url="", score=0.7),
    ]
    out = _dedupe_by_id(refs)
    assert len(out) == 2
    assert out[0]["title"] == "A"  # ilk gelen kalır


def _mk_result(**meta) -> object:
    """Tek satırlık dummy SearchResult — _format_title input'u için."""
    return type(
        "_R",
        (),
        {"chunk_id": meta.pop("chunk_id", "x"), "metadata": meta},
    )()


def test_format_title_law():
    r = _mk_result(kanun_kodu="TKHK", madde_no="11")
    assert _format_title(r) == "TKHK Madde 11"


def test_format_title_case():
    r = _mk_result(court="Yargıtay", esas_no="2019", karar_no="1234")
    assert _format_title(r) == "Yargıtay 2019/1234"


def test_format_title_fallback():
    r = _mk_result(title="Custom Title")
    assert _format_title(r) == "Custom Title"
    r2 = _mk_result(chunk_id="id-only")
    assert _format_title(r2) == "id-only"
