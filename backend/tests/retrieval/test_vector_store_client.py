"""vector_store Qdrant client lifecycle testleri.

`get_shared_client` request path için process-ömürlü TEK client (havuz churn'ünü
önler); `get_client` ise script'ler için her çağrıda YENİ client. Gerçek
Qdrant'a bağlanılmaz — AsyncQdrantClient yaratımı lazy'dir.
"""

from __future__ import annotations

import pytest

from retrieval import vector_store as vs


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Her testten önce/sonra paylaşılan client'ı sıfırla (izolasyon)."""
    vs._reset_shared_client()
    yield
    vs._reset_shared_client()


def test_get_shared_client_returns_same_instance():
    assert vs.get_shared_client() is vs.get_shared_client()


def test_get_client_returns_new_instance_each_call():
    # Script path: her çağrı yeni client (kendi close'unu yönetir).
    assert vs.get_client() is not vs.get_client()


def test_reset_shared_client_forces_new_instance():
    c1 = vs.get_shared_client()
    vs._reset_shared_client()
    assert vs.get_shared_client() is not c1


@pytest.mark.asyncio
async def test_aclose_shared_client_closes_and_resets():
    c1 = vs.get_shared_client()
    await vs.aclose_shared_client()
    # Kapandıktan sonra yeni get_shared_client taze client döndürür.
    assert vs.get_shared_client() is not c1


@pytest.mark.asyncio
async def test_aclose_shared_client_idempotent_when_none():
    vs._reset_shared_client()
    # Singleton yokken çağrı no-op olmalı (hata fırlatmamalı).
    await vs.aclose_shared_client()


@pytest.mark.asyncio
async def test_ensure_collection_indexes_all_filtered_fields():
    """Denetim #2: filtreli arama alanları (doc_type/kanun_kodu/madde_no/chunk_id) payload-
    indexli olmalı — yoksa filtreli sorgu 159K noktayı O(N) brute-force tarar."""
    from unittest.mock import AsyncMock, MagicMock

    from qdrant_client import models

    client = AsyncMock()
    empty = MagicMock()
    empty.collections = []
    client.get_collections = AsyncMock(return_value=empty)

    await vs.ensure_collection(client, enable_colbert=False)

    indexed = {
        c.kwargs["field_name"]: c.kwargs["field_schema"]
        for c in client.create_payload_index.call_args_list
    }
    assert {"domain", "source", "doc_type", "kanun_kodu", "chunk_id", "madde_no"} <= set(indexed)
    assert indexed["madde_no"] == models.PayloadSchemaType.INTEGER  # int payload
    assert indexed["doc_type"] == models.PayloadSchemaType.KEYWORD


@pytest.mark.asyncio
async def test_create_payload_indexes_skip_existing_swallows_errors():
    """Migration helper: önceden seed edilmiş koleksiyonda index zaten varsa
    skip_existing=True hatayı yutar; False ise propagate eder."""
    from unittest.mock import AsyncMock

    client = AsyncMock()
    client.create_payload_index = AsyncMock(side_effect=RuntimeError("already exists"))

    await vs.create_payload_indexes(client, "adalet_mursit_hybrid", skip_existing=True)
    assert client.create_payload_index.await_count == len(vs._PAYLOAD_INDEXES)

    with pytest.raises(RuntimeError):
        await vs.create_payload_indexes(client, "x", skip_existing=False)
