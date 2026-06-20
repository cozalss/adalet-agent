"""agents/nodes/tahmin.py — 8. ajan node davranışı (W18)."""

from __future__ import annotations

import pytest

from agents.nodes.tahmin import _top_unique_case_refs, tahmin_node
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
    # Durumsal şikâyet (genel/bilgi soru-kalıbı İÇERMEZ) → tahmin gösterilir.
    state = {
        "question": "İşten haksız yere çıkarıldım ve tazminatım ödenmedi.",
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
async def test_tahmin_node_general_question_suppressed():
    """Bilgi/usul/tanım sorusunda (emsal olsa bile) tahmin GİZLENİR — dava değil.

    'yasal sınır nedir?' / 'nasıl itiraz ederim?' tipi sorularda 'geçmiş davalar
    %X aleyhe' göstermek yanıltıcı (jüri-riski). prediction=None → kart render olmaz.
    """
    refs = [
        _case("c1", "davanın kabulüne karar verildi"),
        _case("c2", "talebin kabulüne karar verildi"),
    ]
    for q in (
        "Ev sahibim fahiş kira zammı istiyor, yasal sınır nedir?",
        "Hakkımda icra takibi başlatıldı, nasıl itiraz ederim?",
        "Kıdem tazminatı nasıl hesaplanır?",
    ):
        out = await tahmin_node({"question": q, "emsal_refs": refs})
        assert out == {"prediction": None}, f"genel soru tahmin üretmemeli: {q}"


@pytest.mark.asyncio
async def test_tahmin_node_uses_top_k_only():
    """Üst-K (8) limiti: daha fazla emsal verilse de yalnız ilk 8 kullanılır."""
    refs = [_case(f"c{i}", "davanın kabulüne karar verildi") for i in range(12)]
    out = await tahmin_node({"question": "q", "emsal_refs": refs})
    pred = out["prediction"]
    assert pred is not None
    assert len(pred["similar_case_ids"]) == 8


def test_top_unique_case_refs_dedups_chunks_from_same_decision():
    refs = [
        _case("h-1-c0", "a"),
        _case("h-1-c2", "b"),
        _case("h-2-c0", "c"),
        _case("h-3-c1", "d"),
    ]

    out = _top_unique_case_refs(refs, limit=5)

    assert [r["source_id"] for r in out] == ["h-1-c0", "h-2-c0", "h-3-c1"]
