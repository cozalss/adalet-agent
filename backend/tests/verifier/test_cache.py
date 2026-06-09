"""verifier/cache.py — NLI doğrulama cache testleri (bellek fallback yolu)."""

from __future__ import annotations

import pytest

from verifier.cache import (
    VerificationCache,
    nli_cache_key,
    reset_verification_cache,
)


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """REDIS_URL boş → bellek fallback yolu test edilir (deterministik)."""
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("NLI_CACHE_ENABLED", "1")
    reset_verification_cache()
    yield
    reset_verification_cache()


# --- key üretimi ---

def test_key_deterministic():
    k1 = nli_cache_key("2 yıl çalıştım", "İş Kanunu md.14")
    k2 = nli_cache_key("2 yıl çalıştım", "İş Kanunu md.14")
    assert k1 == k2


def test_key_differs_on_claim_or_evidence():
    base = nli_cache_key("claim A", "evidence X")
    assert base != nli_cache_key("claim B", "evidence X")
    assert base != nli_cache_key("claim A", "evidence Y")


def test_key_namespaced_by_model(monkeypatch):
    monkeypatch.setenv("NLI_MODEL", "model-1")
    k1 = nli_cache_key("c", "e")
    monkeypatch.setenv("NLI_MODEL", "model-2")
    k2 = nli_cache_key("c", "e")
    assert k1 != k2  # model değişimi cache namespace'i değiştirir


def test_namespace_reflects_actual_model_without_env(monkeypatch):
    """Denetim #12: NLI_MODEL env'i HİÇ set edilmiyordu (nli.py modeli sabitten seçer) →
    namespace daima hash('default') kalıyordu → model değişince stale veto cache'i servis
    edilirdi. Env yokken namespace GERÇEK yüklenen modeli (nli.NLI_MODEL) yansıtmalı."""
    import hashlib

    import verifier.cache as cache
    import verifier.nli as nli

    monkeypatch.delenv("NLI_MODEL", raising=False)
    monkeypatch.setattr(nli, "NLI_MODEL", "real-model-A")
    key_a = nli_cache_key("c", "e")
    monkeypatch.setattr(nli, "NLI_MODEL", "real-model-B")
    key_b = nli_cache_key("c", "e")
    assert key_a != key_b  # gerçek model değişince namespace değişir
    # ve artık literal 'default' hash'ine düşmemeli
    default_tag = hashlib.sha1(b"default", usedforsecurity=False).hexdigest()[:8]
    assert f":{default_tag}:" not in key_a
    assert cache  # import kullanıldı (lint)


# --- get/set (bellek fallback) ---

def test_set_then_get():
    c = VerificationCache()
    k = nli_cache_key("c1", "e1")
    c.set_many({k: {"l": "entailment", "e": 0.8, "c": 0.05}})
    got = c.get_many([k])
    assert got[k]["c"] == 0.05


def test_get_miss_returns_empty():
    c = VerificationCache()
    assert c.get_many([nli_cache_key("yok", "yok")]) == {}


def test_partial_hit():
    c = VerificationCache()
    k1, k2 = nli_cache_key("a", "x"), nli_cache_key("b", "y")
    c.set_many({k1: {"l": "neutral", "e": 0.3, "c": 0.1}})
    got = c.get_many([k1, k2])
    assert k1 in got and k2 not in got


def test_stats_hit_rate():
    c = VerificationCache()
    k = nli_cache_key("a", "x")
    c.set_many({k: {"l": "entailment", "e": 0.9, "c": 0.0}})
    c.get_many([k])                       # 1 hit
    c.get_many([nli_cache_key("z", "z")])  # 1 miss
    s = c.stats()
    assert s["hits"] == 1 and s["misses"] == 1
    assert s["hit_rate"] == 0.5
    assert s["backend"] == "memory"


def test_disabled_returns_empty(monkeypatch):
    # reload YOK (modül durumunu bozar) → modül-seviyesi sabiti doğrudan patch'le.
    import verifier.cache as vc
    monkeypatch.setattr(vc, "NLI_CACHE_ENABLED", False)
    c = vc.VerificationCache()
    k = vc.nli_cache_key("a", "x")
    c.set_many({k: {"l": "x", "e": 1, "c": 0}})
    assert c.get_many([k]) == {}  # disabled → no-op


def test_memory_lru_bounded():
    c = VerificationCache()
    import verifier.cache as vc
    # _MEM_MAX'tan fazla yaz → eski düşmeli, RAM sabit
    for i in range(vc._MEM_MAX + 50):
        c.set_many({f"adalet:nli:t:{i}": {"l": "x", "e": 0.0, "c": 0.0}})
    assert len(c._mem) <= vc._MEM_MAX
