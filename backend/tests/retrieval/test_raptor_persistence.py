"""RaptorIndex save/load + runtime singleton testleri — Sprint-4 W3.1/3.2."""

from __future__ import annotations

from pathlib import Path

import pytest

from retrieval.raptor import RaptorIndex, RaptorNode


def _make_index_with_nodes() -> RaptorIndex:
    """Build() bypass — manuel inject ile minimal pickle-able index."""
    idx = RaptorIndex()
    idx.tree = {
        0: [
            RaptorNode(
                node_id="L0:a", level=0, text="leaf a",
                embedding=[0.1, 0.2], source_chunk_ids=["chunk-a"],
            ),
            RaptorNode(
                node_id="L0:b", level=0, text="leaf b",
                embedding=[0.3, 0.4], source_chunk_ids=["chunk-b"],
            ),
        ],
        1: [
            RaptorNode(
                node_id="L1:c0", level=1, text="özet ab",
                embedding=[0.2, 0.3], children=["L0:a", "L0:b"],
                source_chunk_ids=["chunk-a", "chunk-b"],
            ),
        ],
    }
    idx.built = True
    return idx


def test_save_and_load_roundtrip(tmp_path: Path):
    """Save → load → identical tree."""
    idx = _make_index_with_nodes()
    out_path = tmp_path / "raptor.pkl"
    idx.save(out_path)
    assert out_path.exists()

    loaded = RaptorIndex.load(out_path)
    assert loaded.built is True
    assert set(loaded.tree.keys()) == {0, 1}
    assert len(loaded.tree[0]) == 2
    assert len(loaded.tree[1]) == 1
    # Node detayı korundu mu
    leaf_a = loaded.tree[0][0]
    assert leaf_a.node_id == "L0:a"
    assert leaf_a.source_chunk_ids == ["chunk-a"]


def test_save_raises_when_not_built(tmp_path: Path):
    idx = RaptorIndex()
    with pytest.raises(RuntimeError, match="build"):
        idx.save(tmp_path / "x.pkl")


def test_load_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        RaptorIndex.load(tmp_path / "nope.pkl")


def test_load_creates_parent_dirs(tmp_path: Path):
    """Save() parent klasör yoksa oluştursun."""
    idx = _make_index_with_nodes()
    deep_path = tmp_path / "nested" / "deeper" / "raptor.pkl"
    idx.save(deep_path)
    assert deep_path.exists()


def test_runtime_singleton_no_pickle_returns_empty(monkeypatch, tmp_path):
    """RAPTOR_ENABLED=1 + pickle yok → boş index döner, exception fırlatmaz."""
    from retrieval import raptor_runtime

    raptor_runtime.reset_raptor_singleton()
    monkeypatch.setattr(raptor_runtime, "RAPTOR_ENABLED", True)
    monkeypatch.setattr(
        raptor_runtime, "RAPTOR_PICKLE_PATH",
        str(tmp_path / "nonexistent.pkl"),
    )
    idx = raptor_runtime.get_raptor_index()
    assert idx is not None
    assert idx.built is False or len(idx.all_nodes()) == 0


def test_runtime_singleton_loads_existing_pickle(monkeypatch, tmp_path):
    """RAPTOR_ENABLED=1 + pickle var → diskten yüklenir."""
    from retrieval import raptor_runtime

    # Mevcut pickle hazırla
    idx = _make_index_with_nodes()
    pickle_path = tmp_path / "tree.pkl"
    idx.save(pickle_path)

    raptor_runtime.reset_raptor_singleton()
    monkeypatch.setattr(raptor_runtime, "RAPTOR_ENABLED", True)
    monkeypatch.setattr(raptor_runtime, "RAPTOR_PICKLE_PATH", str(pickle_path))

    loaded = raptor_runtime.get_raptor_index()
    assert loaded is not None
    assert loaded.built is True
    assert len(loaded.all_nodes()) == 3


def test_runtime_singleton_disabled_returns_none(monkeypatch):
    """RAPTOR_ENABLED=0 → None (no-op)."""
    from retrieval import raptor_runtime

    raptor_runtime.reset_raptor_singleton()
    monkeypatch.setattr(raptor_runtime, "RAPTOR_ENABLED", False)
    assert raptor_runtime.get_raptor_index() is None


def test_runtime_singleton_caches_call(monkeypatch, tmp_path):
    """İkinci çağrı disk'e gitmesin."""
    from retrieval import raptor_runtime

    idx = _make_index_with_nodes()
    pickle_path = tmp_path / "tree.pkl"
    idx.save(pickle_path)

    raptor_runtime.reset_raptor_singleton()
    monkeypatch.setattr(raptor_runtime, "RAPTOR_ENABLED", True)
    monkeypatch.setattr(raptor_runtime, "RAPTOR_PICKLE_PATH", str(pickle_path))

    a = raptor_runtime.get_raptor_index()
    b = raptor_runtime.get_raptor_index()
    assert a is b   # aynı obje (singleton)
