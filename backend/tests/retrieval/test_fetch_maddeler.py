"""fetch_maddeler — (kanun_kodu, madde_no) çiftlerini vektörsüz filtreyle çekme.

Çapa-madde garantisi için: domain'in kilit maddeleri konuşma-dili sorguda
cross-encoder noise-floor yüzünden sıralamaya giremese bile Qdrant'tan doğrudan
çekilir. Gerçek Qdrant'a bağlanılmaz — scroll mock'lanır.
"""

from __future__ import annotations

import pytest

from retrieval import hybrid_search as hs


class _FakePoint:
    def __init__(self, chunk_id: str, kanun_kodu: str, madde_no: int) -> None:
        self.id = chunk_id
        self.score = None  # scroll skorsuz döner
        self.payload = {
            "chunk_id": chunk_id,
            "text": f"madde {madde_no} metni",
            "kanun_kodu": kanun_kodu,
            "madde_no": madde_no,
            "source": "mevzuat",
            "source_url": "https://mevzuat/x",
            "domain": "",
            "doc_type": "law",
        }


class _FakeClient:
    """scroll(should-OR filter) → eşleşen tüm maddeleri TEK çağrıda döndürür.

    Yeni sözleşme: fetch_maddeler N çifti tek scroll'da `should`(OR) ile sorar.
    Mock, should içindeki her nested `must`'tan (kanun_kodu, madde_no) çıkarıp
    store'dan eşleşenleri toplar. `calls` çağrı SAYISINI doğrular (N pair → 1).
    """

    def __init__(self, store: dict[tuple[str, int], _FakePoint]) -> None:
        self._store = store
        self.calls: list[list[tuple[str, int]]] = []

    async def scroll(self, collection_name, scroll_filter, limit, with_payload):
        pairs: list[tuple[str, int]] = []
        for sub in scroll_filter.should:
            kod = sub.must[0].match.value
            madde = sub.must[1].match.value
            pairs.append((kod, madde))
        self.calls.append(pairs)
        found = [self._store[p] for p in pairs if p in self._store]
        return (found, None)


@pytest.fixture
def _patch_client(monkeypatch):
    def _install(store):
        client = _FakeClient(store)
        monkeypatch.setattr(hs, "get_shared_client", lambda: client)
        return client
    return _install


@pytest.mark.asyncio
async def test_fetch_maddeler_returns_matching_maddeler(_patch_client):
    store = {
        ("IK", 17): _FakePoint("m-IK-17", "IK", 17),
        ("EIK", 14): _FakePoint("m-EIK-14", "EIK", 14),
    }
    client = _patch_client(store)
    out = await hs.fetch_maddeler([("IK", 17), ("EIK", 14)])
    assert {r.chunk_id for r in out} == {"m-IK-17", "m-EIK-14"}
    assert all(r.score == 0.0 for r in out)  # skorsuz → 0.0
    # N=2 çift TEK scroll'da çekilir (N+1 değil) — perf garantisi.
    assert len(client.calls) == 1
    assert client.calls[0] == [("IK", 17), ("EIK", 14)]


@pytest.mark.asyncio
async def test_fetch_maddeler_skips_missing(_patch_client):
    """Corpus'ta olmayan madde sessizce atlanır (KeyError/exception YOK)."""
    store = {("IK", 17): _FakePoint("m-IK-17", "IK", 17)}
    _patch_client(store)
    out = await hs.fetch_maddeler([("IK", 17), ("IK", 999)])
    assert [r.chunk_id for r in out] == ["m-IK-17"]


@pytest.mark.asyncio
async def test_fetch_maddeler_empty_input_no_client_call(_patch_client):
    client = _patch_client({})
    out = await hs.fetch_maddeler([])
    assert out == []
    assert client.calls == []  # boş girdide Qdrant'a hiç gidilmez


@pytest.mark.asyncio
async def test_fetch_maddeler_metadata_carries_kanun_kodu(_patch_client):
    """Payload'daki kanun_kodu/madde_no metadata'ya taşınır (tier-sort buna bakar)."""
    store = {("TKHK", 11): _FakePoint("m-TKHK-11", "TKHK", 11)}
    _patch_client(store)
    out = await hs.fetch_maddeler([("TKHK", 11)])
    assert out[0].metadata["kanun_kodu"] == "TKHK"
    assert out[0].metadata["madde_no"] == 11
