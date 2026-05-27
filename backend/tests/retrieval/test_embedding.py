"""embedding.py — EmbedOutput dataclass + (encoder gerçek yüklemeden) testleri.

Gerçek BGE-M3 model yüklemek istemiyoruz (test ortamında ağır). Sadece
EmbedOutput şeması, _lexical_to_sparse helper'ı ve encode_query 3-tuple
signature test edilir.
"""

from __future__ import annotations

import pytest

from retrieval.embedding import Embedder, EmbedOutput, _lexical_to_sparse


def test_embed_output_defaults_colbert_none():
    out = EmbedOutput(dense=[[1.0, 2.0]], sparse=[([0], [0.5])])
    assert out.colbert is None
    assert len(out.dense) == 1


def test_embed_output_with_colbert():
    out = EmbedOutput(
        dense=[[1.0]],
        sparse=[([0], [0.5])],
        colbert=[[[1.0, 2.0], [3.0, 4.0]]],  # 1 doc, 2 tokens, 2-d
    )
    assert out.colbert is not None
    assert len(out.colbert) == 1
    assert len(out.colbert[0]) == 2


def test_lexical_to_sparse_filters_non_positive():
    weights = {"1": 0.5, "2": 0.0, "3": -0.1, "4": 0.3}
    idx, _vals = _lexical_to_sparse(weights)
    # 0.0 ve -0.1 filtre dışı
    assert len(idx) == 2
    assert 1 in idx and 4 in idx
    assert 2 not in idx and 3 not in idx


def test_lexical_to_sparse_empty():
    idx, vals = _lexical_to_sparse({})
    assert idx == []
    assert vals == []


def test_lexical_to_sparse_token_id_int_conversion():
    weights = {"42": 0.7}
    idx, vals = _lexical_to_sparse(weights)
    assert idx == [42]
    assert isinstance(idx[0], int)
    assert vals == [0.7]


# --------------------------------------------------------------------------
#  Async offload wrappers — event loop'u bloke etmeden encode (to_thread).
#  Gerçek model yüklenmez; sync encode() fake'lenir, async sarmalayıcının
#  doğru delege ettiği + şekli koruduğu doğrulanır.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aencode_query_delegates_to_encode(monkeypatch):
    emb = Embedder()

    def fake_encode(texts, batch_size=12, max_length=8192, return_colbert=None):
        assert texts == ["soru"]
        return EmbedOutput(dense=[[0.1, 0.2]], sparse=[([1], [0.5])], colbert=None)

    monkeypatch.setattr(emb, "encode", fake_encode)
    dense, (idx, val), colbert = await emb.aencode_query("soru")
    assert dense == [0.1, 0.2]
    assert idx == [1] and val == [0.5]
    assert colbert is None


@pytest.mark.asyncio
async def test_aencode_batches_all_texts(monkeypatch):
    emb = Embedder()
    captured: dict = {}

    def fake_encode(texts, batch_size=12, max_length=8192, return_colbert=None):
        captured["texts"] = texts
        return EmbedOutput(
            dense=[[1.0], [2.0]], sparse=[([1], [0.1]), ([2], [0.2])], colbert=None,
        )

    monkeypatch.setattr(emb, "encode", fake_encode)
    out = await emb.aencode(["a", "b"])
    # Tek forward'da iki metin birden (HyDE batch yolu).
    assert captured["texts"] == ["a", "b"]
    assert out.dense == [[1.0], [2.0]]
    assert out.sparse[1] == ([2], [0.2])
