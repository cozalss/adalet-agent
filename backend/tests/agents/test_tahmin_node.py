"""agents/nodes/tahmin.py — 8. ajan node davranışı (W18)."""

from __future__ import annotations

import pytest

from agents.nodes.tahmin import tahmin_node
from agents.state import Citation


def _case(source_id: str, snippet: str) -> Citation:
    return Citation(
        source_id=source_id,
        doc_type="case",
        title=f"Yargıtay {source_id}",
        snippet=snippet,
        url=f"https://yargi.gov.tr/{source_id}",
        score=0.8,
    )


@pytest.mark.asyncio
async def test_tahmin_node_no_emsal_returns_none():
    out = await tahmin_node({"question": "soru", "emsal_refs": []})
    assert out == {"prediction": None}


@pytest.mark.asyncio
async def test_tahmin_node_predicts_from_emsal():
    state = {
        "question": "Kıdem tazminatı alabilir miyim?",
        "emsal_refs": [
            _case("c1", "davanın kabulüne karar verildi"),
            _case("c2", "talebin kabulüne karar verildi"),
            _case("c3", "davanın reddine karar verildi"),
        ],
    }
    out = await tahmin_node(state)
    pred = out["prediction"]
    assert pred is not None
    assert pred["verdict_class"] == "kazandi"
    assert pred["similar_case_ids"] == ["c1", "c2", "c3"]
    assert 0.0 < pred["confidence"] <= 0.85


@pytest.mark.asyncio
async def test_tahmin_node_uses_top_k_only():
    """5'ten fazla emsal verilse de yalnız ilk 5 kullanılır."""
    refs = [_case(f"c{i}", "davanın kabulüne karar verildi") for i in range(8)]
    out = await tahmin_node({"question": "q", "emsal_refs": refs})
    pred = out["prediction"]
    assert pred is not None
    assert len(pred["similar_case_ids"]) == 5
