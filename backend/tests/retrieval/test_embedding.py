"""embedding.py — EmbedOutput dataclass + (encoder gerçek yüklemeden) testleri.

Gerçek BGE-M3 model yüklemek istemiyoruz (test ortamında ağır). Sadece
EmbedOutput şeması, _lexical_to_sparse helper'ı ve encode_query 3-tuple
signature test edilir.
"""

from __future__ import annotations

from retrieval.embedding import EmbedOutput, _lexical_to_sparse


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
