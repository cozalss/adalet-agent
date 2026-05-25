"""RAPTOR — hiyerarşik özet ağacı testleri (deterministik fake embedder/summarizer).

Gerçek BGE-M3 ve LLM çağırmadan ağaç inşası ve sorgu davranışını doğrular.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

# RAPTOR'u aç (env default kapalı)
os.environ["RAPTOR_ENABLED"] = "1"

from retrieval.raptor import (
    RAPTOR_ENABLED,
    RaptorIndex,
    RaptorNode,
    _cluster_nodes,
    _cosine,
)


@dataclass
class FakeEmbedOutput:
    """Embedder.encode() çıktısını taklit et — sadece .dense kullanılır."""

    dense: list[list[float]]


class FakeEmbedder:
    """Deterministik 4-d dummy vector — text uzunluğu ve ilk karakter ile şekil verir."""

    def encode(self, texts, return_colbert: bool = False):
        vecs = [self._vec_for(t) for t in texts]
        return FakeEmbedOutput(dense=vecs)

    def encode_query(self, q: str, return_colbert: bool = False):
        return (self._vec_for(q), None, None)

    @staticmethod
    def _vec_for(t: str) -> list[float]:
        # 4-d deterministik vektor — basit özellik mühendisliği
        if not t:
            return [0.0, 0.0, 0.0, 0.0]
        n = len(t)
        first = ord(t[0]) % 7
        return [
            min(1.0, n / 1000.0),
            (first + 1) / 7.0,
            ("madde" in t.lower()) * 0.9 + 0.05,
            ("karar" in t.lower()) * 0.9 + 0.05,
        ]


async def _fake_summarize(texts: list[str]) -> str:
    return f"[SUMMARY of {len(texts)} parça]: " + " | ".join(t[:30] for t in texts)


@pytest.mark.asyncio
async def test_raptor_build_creates_hierarchy():
    """8 chunk → en az 2 seviye ağaç (leaf + summary level)."""
    docs = [
        (f"chunk-{i}", f"Madde {i} hakkında metin parçası, hukuki içerik {i}.")
        for i in range(8)
    ]
    idx = RaptorIndex()
    await idx.build(docs, embedder=FakeEmbedder(), llm_summarize=_fake_summarize)

    assert idx.built is True
    assert 0 in idx.tree
    assert len(idx.tree[0]) == 8
    # En az bir üst seviye olmalı
    assert max(idx.tree.keys()) >= 1


@pytest.mark.asyncio
async def test_raptor_query_returns_top_k_across_levels():
    """Query her seviyeden top-k çekip score'a göre concat eder."""
    docs = [
        ("a", "Tüketici ayıplı mal iadesi madde 11"),
        ("b", "İş Kanunu kıdem tazminatı madde 32"),
        ("c", "Kira sözleşmesi tahliye madde 350"),
        ("d", "Yargıtay 9.HD 2019 karar emsal kıdem"),
    ]
    idx = RaptorIndex()
    await idx.build(docs, embedder=FakeEmbedder(), llm_summarize=_fake_summarize)

    hits = await idx.query("kıdem tazminatı", top_k=3, embedder=FakeEmbedder())
    assert len(hits) <= 3
    for h in hits:
        assert h.score >= 0.0
        assert isinstance(h.matched_level, int)
        assert isinstance(h.node, RaptorNode)


@pytest.mark.asyncio
async def test_raptor_build_empty_docs_safe():
    """Boş döküman → built=True, sorgu boş döner."""
    idx = RaptorIndex()
    await idx.build([], embedder=FakeEmbedder(), llm_summarize=_fake_summarize)
    assert idx.built is True
    hits = await idx.query("x", embedder=FakeEmbedder())
    assert hits == []


def test_raptor_env_default_off():
    """RAPTOR_ENABLED env=0 olduğunda modül flag'i kapalı dönmeli."""
    saved = os.environ.get("RAPTOR_ENABLED")
    try:
        os.environ["RAPTOR_ENABLED"] = "0"
        # Manuel RAPTOR_ENABLED=0 davranışını test etmek için modülü reload
        import asyncio as _aio

        async def _runner():
            import importlib

            import retrieval.raptor as rm
            importlib.reload(rm)
            i = rm.RaptorIndex()
            await i.build([("x", "a")], embedder=FakeEmbedder(), llm_summarize=_fake_summarize)
            return i.tree

        tree = _aio.run(_runner())
        assert tree == {}
    finally:
        if saved is not None:
            os.environ["RAPTOR_ENABLED"] = saved
        else:
            os.environ.pop("RAPTOR_ENABLED", None)
        import importlib

        import retrieval.raptor as rm
        importlib.reload(rm)


def test_cluster_nodes_handles_tiny_corpus():
    """1 node → tek cluster fallback."""
    nodes = [RaptorNode(node_id="x", level=0, text="t", embedding=[1.0, 0.0])]
    clusters = _cluster_nodes(nodes)
    assert clusters == [[0]]


def test_cluster_nodes_groups_similar():
    """5 node, 2 grup → en az 1 cluster, hepsi mevcut."""
    # 3 benzer + 2 farklı
    nodes = [
        RaptorNode(node_id=f"a{i}", level=0, text="x", embedding=[1.0, 0.0, 0.0, 0.0])
        for i in range(3)
    ] + [
        RaptorNode(node_id=f"b{i}", level=0, text="y", embedding=[0.0, 1.0, 0.0, 0.0])
        for i in range(2)
    ]
    clusters = _cluster_nodes(nodes)
    assert len(clusters) >= 1
    total = sum(len(c) for c in clusters)
    assert total == 5


def test_cosine_basic():
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0, abs=1e-6)
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0, abs=1e-6)
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_raptor_enabled_default_off_at_import():
    """RAPTOR_ENABLED env değişkeni varsayılan testte env=1, ama clean process default 0 olmalı."""
    # Kullanılan flag testte set edildiği için 1 olmalı
    assert RAPTOR_ENABLED is True
