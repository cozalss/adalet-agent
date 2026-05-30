"""retrieval/adaptive_router.py birim testleri.

A/B verisiyle kalibre edilmiş routing kararlarını ve karmaşıklık skorlarını doğrular.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from retrieval.adaptive_router import RoutingDecision, _query_complexity, route_query


# ---------------------------------------------------------------------------
# 1. _query_complexity — karmaşıklık puanı
# ---------------------------------------------------------------------------

def test_law_reference_yields_low_complexity():
    # Kanun/madde referansı → zaten spesifik, HyDE gerekmez
    assert _query_complexity("TKHK madde 11 uyarınca taleplerim neler?") < 0.4


def test_very_short_query_yields_low_complexity():
    assert _query_complexity("kira artış") < 0.4


def test_conversational_query_yields_high_complexity():
    q = "depozitomu geri alamıyorum ne yapabilirim hakkım var mı"
    assert _query_complexity(q) >= 0.7


def test_long_scenario_yields_high_complexity():
    q = " ".join(["kelime"] * 15)  # 15 kelimelik soru
    assert _query_complexity(q) >= 0.7


def test_medium_query_yields_medium_complexity():
    q = "işten çıkarıldım tazminat alabilir miyim"
    score = _query_complexity(q)
    assert 0.3 < score < 0.9


def test_ik_reference_yields_low_complexity():
    assert _query_complexity("ik madde 17 kapsamında bildirim süresi nedir") < 0.4


# ---------------------------------------------------------------------------
# 2. route_query — adaptive routing kapalıyken (legacy mod)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_env(monkeypatch):
    """Her test için env'i temizle — test izolasyonu."""
    monkeypatch.setenv("ADAPTIVE_ROUTING_ENABLED", "1")
    monkeypatch.setenv("HYDE_ENABLED", "1")
    monkeypatch.setenv("MULTI_QUERY_ENABLED", "1")
    monkeypatch.setenv("HYDE_ENABLED_DOMAINS", "tuketici,kira,isHukuku,vergi")
    monkeypatch.setenv("MULTI_QUERY_ENABLED_DOMAINS", "trafik,kira,idari")
    monkeypatch.setenv("QUERY_COMPLEXITY_THRESHOLD", "0.4")


def test_route_returns_routing_decision():
    with patch("retrieval.adaptive_router.ADAPTIVE_ROUTING_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED", True), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED_DOMAINS", frozenset({"tuketici", "kira", "isHukuku", "vergi"})), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED_DOMAINS", frozenset({"trafik", "kira", "idari"})), \
         patch("retrieval.adaptive_router.QUERY_COMPLEXITY_THRESHOLD", 0.4):
        decision = route_query("depozitomu geri alamıyorum ne yapabilirim", "kira")
    assert isinstance(decision, RoutingDecision)


# ---------------------------------------------------------------------------
# 3. HyDE domain whitelist
# ---------------------------------------------------------------------------

def test_hyde_enabled_for_whitelisted_domain_complex_query():
    with patch("retrieval.adaptive_router.ADAPTIVE_ROUTING_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED", True), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED", False), \
         patch("retrieval.adaptive_router.HYDE_ENABLED_DOMAINS", frozenset({"tuketici", "kira", "isHukuku", "vergi"})), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED_DOMAINS", frozenset()), \
         patch("retrieval.adaptive_router.QUERY_COMPLEXITY_THRESHOLD", 0.4):
        dec = route_query("aldığım ürün bozuk garanti kapsamında ne yapabilirim", "tuketici")
    assert dec.use_hyde is True
    assert dec.strategy == "hyde"


def test_hyde_disabled_for_harmful_domain():
    # trafik A/B'de -20pp → whitelist dışında
    with patch("retrieval.adaptive_router.ADAPTIVE_ROUTING_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED", True), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED", False), \
         patch("retrieval.adaptive_router.HYDE_ENABLED_DOMAINS", frozenset({"tuketici", "kira", "isHukuku", "vergi"})), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED_DOMAINS", frozenset()), \
         patch("retrieval.adaptive_router.QUERY_COMPLEXITY_THRESHOLD", 0.4):
        dec = route_query("kaza yaptım sigorta ödeme yapmıyor ne yapabilirim", "trafik")
    assert dec.use_hyde is False


def test_hyde_disabled_for_idari_domain():
    with patch("retrieval.adaptive_router.ADAPTIVE_ROUTING_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED", True), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED", False), \
         patch("retrieval.adaptive_router.HYDE_ENABLED_DOMAINS", frozenset({"tuketici", "kira", "isHukuku", "vergi"})), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED_DOMAINS", frozenset()), \
         patch("retrieval.adaptive_router.QUERY_COMPLEXITY_THRESHOLD", 0.4):
        dec = route_query("memuriyetten çıkarıldım ne yapabilirim itiraz hakkım var mı", "idari")
    assert dec.use_hyde is False


# ---------------------------------------------------------------------------
# 4. Multi-Query domain whitelist
# ---------------------------------------------------------------------------

def test_mq_enabled_for_trafik():
    with patch("retrieval.adaptive_router.ADAPTIVE_ROUTING_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED", False), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED_DOMAINS", frozenset()), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED_DOMAINS", frozenset({"trafik", "kira", "idari"})), \
         patch("retrieval.adaptive_router.QUERY_COMPLEXITY_THRESHOLD", 0.4):
        dec = route_query("kaza yaptım karşı araç sigortası ödeme yapmıyor ne yapabilirim", "trafik")
    assert dec.use_mq is True
    assert dec.strategy == "mq"


def test_mq_disabled_for_tuketici():
    # tuketici A/B'de -18pp → whitelist dışında
    with patch("retrieval.adaptive_router.ADAPTIVE_ROUTING_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED", False), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED_DOMAINS", frozenset()), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED_DOMAINS", frozenset({"trafik", "kira", "idari"})), \
         patch("retrieval.adaptive_router.QUERY_COMPLEXITY_THRESHOLD", 0.4):
        dec = route_query("aldığım ürün bozuk garanti kapsamında tazminat alabilir miyim", "tuketici")
    assert dec.use_mq is False


# ---------------------------------------------------------------------------
# 5. Kira — hem HyDE hem MQ kazandığı alan
# ---------------------------------------------------------------------------

def test_kira_both_hyde_and_mq():
    with patch("retrieval.adaptive_router.ADAPTIVE_ROUTING_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED", True), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED_DOMAINS", frozenset({"tuketici", "kira", "isHukuku", "vergi"})), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED_DOMAINS", frozenset({"trafik", "kira", "idari"})), \
         patch("retrieval.adaptive_router.QUERY_COMPLEXITY_THRESHOLD", 0.4):
        dec = route_query("ev sahibi depozitomu geri vermiyor ne yapabilirim hakkım nedir", "kira")
    assert dec.use_hyde is True
    assert dec.use_mq is True
    assert dec.strategy == "hyde+mq"


# ---------------------------------------------------------------------------
# 6. Karmaşıklık eşiği altında — genişletme yok
# ---------------------------------------------------------------------------

def test_low_complexity_bypasses_expansion():
    # Kısa sorgu bile whitelist'te domain olsa genişletme almamalı
    with patch("retrieval.adaptive_router.ADAPTIVE_ROUTING_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED", True), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED_DOMAINS", frozenset({"tuketici"})), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED_DOMAINS", frozenset({"tuketici"})), \
         patch("retrieval.adaptive_router.QUERY_COMPLEXITY_THRESHOLD", 0.4):
        dec = route_query("TKHK m.11", "tuketici")  # kanun ref → complexity 0.15
    assert dec.use_hyde is False
    assert dec.use_mq is False
    assert dec.strategy == "hybrid"


# ---------------------------------------------------------------------------
# 7. Legacy mod (ADAPTIVE_ROUTING_ENABLED=0)
# ---------------------------------------------------------------------------

def test_legacy_mode_uses_global_flags():
    with patch("retrieval.adaptive_router.ADAPTIVE_ROUTING_ENABLED", False), \
         patch("retrieval.adaptive_router.HYDE_ENABLED", True), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED", True), \
         patch("retrieval.adaptive_router.HYDE_ENABLED_DOMAINS", frozenset()), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED_DOMAINS", frozenset()), \
         patch("retrieval.adaptive_router.QUERY_COMPLEXITY_THRESHOLD", 0.4):
        # domain whitelist boş ama legacy modda global flag'ler geçerli
        dec = route_query("kaza yaptım ne yapabilirim", "trafik")
    assert dec.use_hyde is True
    assert dec.use_mq is True
    assert dec.strategy == "hyde+mq"


def test_legacy_mode_global_disabled():
    with patch("retrieval.adaptive_router.ADAPTIVE_ROUTING_ENABLED", False), \
         patch("retrieval.adaptive_router.HYDE_ENABLED", False), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED", False), \
         patch("retrieval.adaptive_router.HYDE_ENABLED_DOMAINS", frozenset({"tuketici"})), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED_DOMAINS", frozenset({"tuketici"})), \
         patch("retrieval.adaptive_router.QUERY_COMPLEXITY_THRESHOLD", 0.4):
        dec = route_query("aldığım ürün bozuk ne yapabilirim", "tuketici")
    assert dec.use_hyde is False
    assert dec.use_mq is False
    assert dec.strategy == "hybrid"


# ---------------------------------------------------------------------------
# 8. strategy string doğruluğu
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hyde,mq,expected_strategy", [
    (True, True, "hyde+mq"),
    (True, False, "hyde"),
    (False, True, "mq"),
    (False, False, "hybrid"),
])
def test_strategy_string(hyde, mq, expected_strategy):
    with patch("retrieval.adaptive_router.ADAPTIVE_ROUTING_ENABLED", False), \
         patch("retrieval.adaptive_router.HYDE_ENABLED", hyde), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED", mq), \
         patch("retrieval.adaptive_router.HYDE_ENABLED_DOMAINS", frozenset()), \
         patch("retrieval.adaptive_router.MULTI_QUERY_ENABLED_DOMAINS", frozenset()), \
         patch("retrieval.adaptive_router.QUERY_COMPLEXITY_THRESHOLD", 0.4):
        dec = route_query("test sorgu karmaşıklık testi için orta uzunluk", "kira")
    assert dec.strategy == expected_strategy
