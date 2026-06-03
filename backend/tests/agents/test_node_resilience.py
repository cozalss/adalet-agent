"""Fan-in retrieval dayanıklılığı — paralel mevzuat/emsal node'ları (denetim 2026-06-04).

Eskiden birincil retrieval beklenmedik bir exception fırlatırsa (embedding RuntimeError,
Qdrant ValueError, reranker AttributeError) node raise ediyor → graph.ainvoke komple
çöküyor → /ask 500, kısmi cevap bile dönmüyordu. Artık her node beklenmedik hatayı yakalar,
boş refs + errors döndürür; diğer kol + verify ayakta kalır (dejenere ama yanıt üretir).
"""

from __future__ import annotations

import agents.nodes.emsal as emsal_mod
import agents.nodes.mevzuat as mevzuat_mod


async def test_emsal_node_degrades_on_unexpected_error(monkeypatch):
    async def boom(*_a, **_k):
        raise ValueError("simulated embedding/Qdrant failure")

    monkeypatch.setattr(emsal_mod, "_emsal_retrieve", boom)
    out = await emsal_mod.emsal_node({"question": "tahliye davası", "domain": "kira"})
    assert out["emsal_refs"] == []                       # akış çökmedi
    assert out.get("errors") and "emsal" in out["errors"][0]  # hata kaydedildi


async def test_mevzuat_node_degrades_on_unexpected_error(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("simulated reranker AttributeError")

    monkeypatch.setattr(mevzuat_mod, "_mevzuat_retrieve", boom)
    out = await mevzuat_mod.mevzuat_node({"question": "kira artış oranı", "domain": "kira"})
    assert out["mevzuat_refs"] == []
    assert out.get("errors") and "mevzuat" in out["errors"][0]


async def test_nodes_unknown_domain_short_circuit_without_error():
    """unknown domain erken-return: boş refs, errors YOK (dejenerasyon değil, normal)."""
    e = await emsal_mod.emsal_node({"question": "x", "domain": "unknown"})
    m = await mevzuat_mod.mevzuat_node({"question": "x", "domain": "unknown"})
    assert e == {"emsal_refs": []}
    assert m == {"mevzuat_refs": []}
