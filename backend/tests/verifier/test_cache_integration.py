"""layer3_nli_batch cache entegrasyonu — cache'lenmiş pair NLI'a GİTMEMELİ.

Asıl değer testi: ikinci özdeş çağrıda verify_batch boş/eksik pair'le çağrılır
(cache hit), NLI tekrar koşmaz → hız kazancı.
"""

from __future__ import annotations

import pytest

from agents.verifier_layers import layer3_nli_batch
from verifier.cache import reset_verification_cache
from verifier.nli import NLIResult


def _claim(text: str) -> dict:
    return {"text": text, "cite_ids": ["c1"], "verified": False,
            "verify_score": 0.0, "verify_reason": ""}


def _cit(cid: str, snippet: str) -> dict:
    return {"source_id": cid, "doc_type": "law", "title": "T", "snippet": snippet,
            "url": "", "score": 0.9}


class _SpyVerifier:
    """verify_batch çağrılarını ve gelen pair sayısını kaydeder."""

    def __init__(self):
        self.calls: list[int] = []  # her çağrıdaki pair sayısı

    def verify_batch(self, pairs, batch_size=16):
        self.calls.append(len(pairs))
        return [NLIResult(label="entailment", score=0.9, entailment_score=0.85,
                          neutral_score=0.1, contradiction_score=0.05) for _ in pairs]


@pytest.fixture(autouse=True)
def _mem_cache(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")        # bellek fallback
    monkeypatch.setenv("NLI_CACHE_ENABLED", "1")
    reset_verification_cache()
    yield
    reset_verification_cache()


def test_second_call_hits_cache_skips_nli(monkeypatch):
    spy = _SpyVerifier()
    monkeypatch.setattr("agents.verifier_layers.get_verifier", lambda: spy, raising=False)

    claims = [_claim("İşçi kıdem tazminatına hak kazanır")]
    refs = [_cit("c1", "İş Kanunu madde 14 kıdem tazminatı düzenler")]

    # 1. çağrı → cache boş → NLI 1 pair'le çağrılır
    out1 = layer3_nli_batch(claims, refs)
    assert spy.calls == [1]
    assert out1[0][1] == 0.85  # entailment skoru

    # 2. özdeş çağrı → cache hit → NLI HİÇ çağrılmaz (yeni call yok)
    out2 = layer3_nli_batch(claims, refs)
    assert spy.calls == [1]     # ← ikinci verify_batch çağrısı YOK
    assert out2 == out1          # sonuç aynı


def test_partial_cache_only_uncached_to_nli(monkeypatch):
    spy = _SpyVerifier()
    monkeypatch.setattr("agents.verifier_layers.get_verifier", lambda: spy, raising=False)

    refs = [_cit("c1", "kıdem tazminatı madde 14"),
            _cit("c2", "ihbar tazminatı madde 17")]

    # İlk claim'i cache'le
    layer3_nli_batch([_claim("kıdem hakkı")], [refs[0]])
    assert spy.calls == [1]

    # İki claim: biri cache'te, biri yeni → NLI yalnız 1 yeni pair almalı
    out = layer3_nli_batch([_claim("kıdem hakkı"), _claim("ihbar hakkı")], refs)
    assert spy.calls == [1, 1]   # ikinci çağrı yalnız 1 (yeni) pair
    assert len(out) == 2


def test_threshold_applied_at_read_not_cache(monkeypatch):
    """RAW skor cache'lenir; contradiction eşiği okuma anında uygulanır."""
    spy = _SpyVerifier()
    # contradiction yüksek dönen verifier
    def _contra_batch(pairs, batch_size=16):
        spy.calls.append(len(pairs))
        return [NLIResult(label="contradiction", score=0.9, entailment_score=0.05,
                          neutral_score=0.1, contradiction_score=0.85) for _ in pairs]
    spy.verify_batch = _contra_batch
    monkeypatch.setattr("agents.verifier_layers.get_verifier", lambda: spy, raising=False)

    claims = [_claim("yanlış iddia")]
    refs = [_cit("c1", "kaynak metni")]
    out = layer3_nli_batch(claims, refs)
    # contradiction_score 0.85 >= eşik 0.70 → contradicted True
    assert out[0][0] is True
    assert out[0][2] == 0.85
