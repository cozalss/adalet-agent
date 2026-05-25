"""RARR-lite (verifier/rarr.py) unit testleri — Sprint-4 W5.4."""

from __future__ import annotations

import pytest

import verifier.rarr as rarr_mod
from agents.state import Citation, Claim


@pytest.fixture
def _enable_rarr(monkeypatch):
    monkeypatch.setattr(rarr_mod, "RARR_ENABLED", True)


@pytest.mark.asyncio
async def test_rarr_disabled_returns_zero():
    """RARR_ENABLED=False ise her durumda 0 dönmeli."""
    claims = [Claim(text="a" * 50, cite_ids=[], verified=False,
                    verify_score=0.0, verify_reason="")]
    refs: list[Citation] = []
    n = await rarr_mod.augment_evidence_batch(claims, refs)
    assert n == 0
    assert refs == []


@pytest.mark.asyncio
async def test_rarr_empty_claims_returns_zero(_enable_rarr):
    n = await rarr_mod.augment_evidence_batch([], [])
    assert n == 0


@pytest.mark.asyncio
async def test_rarr_skips_claims_with_cite_ids(_enable_rarr, monkeypatch):
    """cite_ids dolu olan claim'ler için search çağrılmamalı."""
    search_called = []

    async def _fake_search(question, top_k):
        search_called.append(question)
        return []

    monkeypatch.setattr("retrieval.hybrid_search.search", _fake_search, raising=False)

    claims = [Claim(
        text="Madde 11 anlamı budur ve uzun bir claim metnidir.",
        cite_ids=["already-here"], verified=False, verify_score=0.0, verify_reason="",
    )]
    refs: list[Citation] = []
    n = await rarr_mod.augment_evidence_batch(claims, refs)
    assert n == 0
    assert search_called == []


@pytest.mark.asyncio
async def test_rarr_skips_short_claims(_enable_rarr, monkeypatch):
    """30 karakterden kısa claim'ler atlanmalı."""
    search_called = []

    async def _fake_search(question, top_k):
        search_called.append(question)
        return []

    monkeypatch.setattr("retrieval.hybrid_search.search", _fake_search, raising=False)

    claims = [Claim(text="kısa", cite_ids=[], verified=False,
                    verify_score=0.0, verify_reason="")]
    n = await rarr_mod.augment_evidence_batch(claims, [])
    assert n == 0
    assert search_called == []


@pytest.mark.asyncio
async def test_rarr_appends_new_snippet(_enable_rarr, monkeypatch):
    """Hybrid search'ten gelen yeni snippet refs'e eklenmeli."""

    class FakeResult:
        chunk_id = "new-chunk-1"
        text = "Madde 32 ücret ödenmesini düzenler."
        score = 0.82
        source = "mevzuat"
        source_url = "https://m/IK/32"
        metadata = {"doc_type": "law", "kanun_kodu": "4857", "madde_no": "32"}

    async def _fake_search(question, top_k):
        return [FakeResult()]

    monkeypatch.setattr("retrieval.hybrid_search.search", _fake_search, raising=False)

    claims = [Claim(
        text="İşveren ücret ödeme yükümlülüğüne sahiptir ve gecikme olamaz.",
        cite_ids=[], verified=False, verify_score=0.0, verify_reason="",
    )]
    refs: list[Citation] = []
    n = await rarr_mod.augment_evidence_batch(claims, refs)
    assert n == 1
    assert len(refs) == 1
    assert refs[0]["source_id"] == "new-chunk-1"
    assert refs[0]["doc_type"] == "law"


@pytest.mark.asyncio
async def test_rarr_dedup_existing_source_id(_enable_rarr, monkeypatch):
    """Aynı source_id zaten varsa eklenmemeli."""

    class FakeResult:
        chunk_id = "existing-id"
        text = "x" * 100
        score = 0.9
        source = "mevzuat"
        source_url = "https://x"
        metadata = {"doc_type": "law"}

    async def _fake_search(question, top_k):
        return [FakeResult()]

    monkeypatch.setattr("retrieval.hybrid_search.search", _fake_search, raising=False)

    refs: list[Citation] = [Citation(
        source_id="existing-id", doc_type="law", title="x",
        snippet="x", url="x", score=0.5,
    )]
    claims = [Claim(
        text="Uzun claim metni en az otuz karakter olmalı bu yeterince uzun.",
        cite_ids=[], verified=False, verify_score=0.0, verify_reason="",
    )]
    n = await rarr_mod.augment_evidence_batch(claims, refs)
    assert n == 0
    assert len(refs) == 1


@pytest.mark.asyncio
async def test_rarr_max_claims_limit(_enable_rarr, monkeypatch):
    """RARR_MAX_CLAIMS aşınca durmalı."""
    call_count = []

    async def _fake_search(question, top_k):
        call_count.append(question)
        return []

    monkeypatch.setattr("retrieval.hybrid_search.search", _fake_search, raising=False)
    monkeypatch.setattr(rarr_mod, "RARR_MAX_CLAIMS", 2)

    claims = [Claim(
        text=f"Claim numarası {i} ve bu yeterince uzun bir metindir.",
        cite_ids=[], verified=False, verify_score=0.0, verify_reason="",
    ) for i in range(5)]
    await rarr_mod.augment_evidence_batch(claims, [])
    assert len(call_count) == 2


@pytest.mark.asyncio
async def test_rarr_search_exception_continues(_enable_rarr, monkeypatch):
    """Search exception tek claim'i atlamalı, diğerlerine devam etmeli."""

    class FakeResult:
        chunk_id = "ok-chunk"
        text = "x" * 100
        score = 0.7
        source = "emsal"
        source_url = "https://x"
        metadata = {"doc_type": "case"}

    call_count = []

    async def _fake_search(question, top_k):
        call_count.append(question)
        if len(call_count) == 1:
            raise RuntimeError("simulated fail")
        return [FakeResult()]

    monkeypatch.setattr("retrieval.hybrid_search.search", _fake_search, raising=False)

    claims = [Claim(
        text=f"İddia numarası {i} ve yeterince uzun bir metindir burada.",
        cite_ids=[], verified=False, verify_score=0.0, verify_reason="",
    ) for i in range(2)]
    n = await rarr_mod.augment_evidence_batch(claims, [])
    assert n == 1
    assert len(call_count) == 2


def test_format_title_with_kod_madde():
    """_format_title kod+madde varsa birleştirir."""

    class FakeSR:
        metadata = {"kanun_kodu": "4857", "madde_no": "32"}
        source = "mevzuat"
        chunk_id = "x"

    assert rarr_mod._format_title(FakeSR()) == "4857 32"


def test_format_title_falls_back_to_chunk_id():
    """meta boşsa chunk_id döner."""

    class FakeSR:
        metadata = {}
        source = None
        chunk_id = "the-id"

    assert rarr_mod._format_title(FakeSR()) == "the-id"
