"""LettuceDetector — token-grounding wrapper + fallback testleri.

Gerçek HF model ağır (~700MB) — testlerde yüklenmez. Pipeline=None senaryosu
(fallback rapidfuzz) test edilir; ayrıca _fallback_token_coverage doğrudan.
"""

from __future__ import annotations

import pytest

from verifier import lettuce as ld


@pytest.mark.asyncio
async def test_fallback_token_coverage_high_overlap():
    det = ld.LettuceDetector(enabled=False)
    # enabled=False → _pipeline None → fallback yolu
    r = await det.grounding_score(
        claim="tüketici ayıplı mal iade hakkı sözleşmeden dönme",
        evidences=[
            "tüketici ayıplı bir mal nedeniyle satıcıdan iade veya "
            "sözleşmeden dönme veya hakkı talep edebilir",
        ],
    )
    assert r.fallback_used is True
    # claim 6 token, hemen hemen hepsi evidence'da → yüksek skor
    assert r.grounding_score >= 0.6


@pytest.mark.asyncio
async def test_fallback_token_coverage_low_overlap():
    det = ld.LettuceDetector(enabled=False)
    r = await det.grounding_score(
        claim="apollo görevi 1969'da aya iniş yapmıştır",
        evidences=["tüketici ayıplı mal iade hakkı vardır"],
    )
    assert r.fallback_used is True
    assert r.grounding_score < 0.5


@pytest.mark.asyncio
async def test_empty_claim_returns_perfect_score():
    det = ld.LettuceDetector(enabled=False)
    r = await det.grounding_score("", ["herhangi bir evidence"])
    assert r.grounding_score == 1.0
    assert r.n_total == 0


@pytest.mark.asyncio
async def test_no_evidences_returns_zero():
    det = ld.LettuceDetector(enabled=False)
    r = await det.grounding_score("bir iddia", [])
    assert r.grounding_score == 0.0
    assert r.fallback_used is True


@pytest.mark.asyncio
async def test_disabled_detector_uses_fallback():
    det = ld.LettuceDetector(enabled=False)
    r = await det.grounding_score(
        claim="tüketici iade hakkına sahiptir",
        evidences=["tüketici iade talep edebilir"],
    )
    assert r.fallback_used is True
    assert r.grounding_score >= 0.0


@pytest.mark.asyncio
async def test_grounding_score_batch_disabled():
    det = ld.LettuceDetector(enabled=False)
    pairs = [
        ("claim1 ile evidence1 tamamen alakalı", ["claim1 ile evidence1 tamamen alakalı"]),
        ("alakasız metin", ["başka bir konu"]),
    ]
    results = await det.grounding_score_batch(pairs)
    assert len(results) == 2
    assert results[0].grounding_score > 0.5  # tam overlap
    assert results[1].grounding_score < 0.5  # no overlap


@pytest.mark.asyncio
async def test_enabled_default_uses_evidence_aware_coverage():
    """W22 (H3 fix): enabled=True ama use_raw_model=False → ham model YÜKLENMEZ,
    grounding kaynak-farkında token-coverage ile yapılır (claim-only değil)."""
    det = ld.LettuceDetector(enabled=True)  # use_raw_model default False
    assert det._pipeline is None  # ham model yüklenmedi

    # Kaynakla örtüşen claim → yüksek; alakasız → düşük (evidence GERÇEKTEN kullanılıyor)
    high = await det.grounding_score(
        claim="tüketici ayıplı mal iade sözleşmeden dönme",
        evidences=["tüketici ayıplı mal nedeniyle iade veya sözleşmeden dönme hakkına sahiptir"],
    )
    low = await det.grounding_score(
        claim="apollo aya iniş roket astronot",
        evidences=["tüketici ayıplı mal nedeniyle iade veya sözleşmeden dönme hakkına sahiptir"],
    )
    assert high.grounding_score > low.grounding_score
    assert high.grounding_score >= 0.6


def test_tokenize_turkish_dotted_i_no_combining_mark():
    """tr_lower: 'İ' → 'i' (combining dot U+0307 ÜRETİLMEMELİ)."""
    tokens = ld._tokenize("İŞÇİ TAZMİNATI İCRA")
    assert "işçi" in tokens
    assert "icra" in tokens
    assert all("̇" not in t for t in tokens)


def test_tokenize_filters_short():
    tokens = ld._tokenize("Bir iki çok uzun kelime evet")
    # "Bir", "iki" 3 ve 3 char — >2 filter → kalır
    # Aslında: len > 2 means keep. "Bir"=3, "iki"=3 stay
    assert "bir" in tokens
    assert "iki" in tokens
    assert "çok" in tokens
    assert "uzun" in tokens
    assert "kelime" in tokens


def test_tokenize_lowercases_turkish():
    tokens = ld._tokenize("MADDE Kıdem TAZMİNATI")
    assert "madde" in tokens
    assert "kıdem" in tokens
    # Türkçe büyük "İ" → küçük "i̇" olabilir locale'a göre — basit kontrol:
    assert any("tazm" in t for t in tokens)
