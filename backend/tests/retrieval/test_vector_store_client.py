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
