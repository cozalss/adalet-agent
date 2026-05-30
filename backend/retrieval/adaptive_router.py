"""Adaptive retrieval routing — sorgu karmaşıklığı ve domain bazlı HyDE/MQ seçimi.

Neden adaptif?
  HyDE ve Multi-Query'yi global açmak bazı domainlerde performansı düşürür:
    HyDE kazandığı: tuketici +12.5pp, kira +14.3pp, vergi +20pp
    HyDE kaybettiği: trafik -20pp, idari -17pp
    MQ kazandığı:   trafik +20pp, kira +14.3pp
    MQ kaybettiği:  tuketici -18pp, vergi -40pp
  Kaynak: A/B ölçüm (2026-05-30, v1 50 vaka, Qwen 14B Q5_K_M)

Routing kararı üç faktöre dayanır:
  1. Master switch: HYDE_ENABLED / MULTI_QUERY_ENABLED env var
  2. Domain whitelist: HYDE_ENABLED_DOMAINS / MULTI_QUERY_ENABLED_DOMAINS
  3. Sorgu karmaşıklığı: kanun referanslı / çok kısa sorgular genişletmeden yararlanmaz
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

from agents.config import (
    ADAPTIVE_ROUTING_ENABLED,
    HYDE_ENABLED,
    HYDE_ENABLED_DOMAINS,
    MULTI_QUERY_ENABLED,
    MULTI_QUERY_ENABLED_DOMAINS,
    QUERY_COMPLEXITY_THRESHOLD,
)

log = structlog.get_logger()

# Türkçe kanun/madde referans kalıpları — bunlar zaten spesifik, genişletme gereksiz.
_LAW_REF_RE = re.compile(
    r"""
    \b(?:
        madde|m\.|             # genel madde referansı
        tkhk|ik\b|tbk|ttk|    # sık kullanılan kanun kodları
        sgk|iik|kmk|kvkk|     # sosyal güvenlik, icra, kat mülkiyeti, KVKK
        vuk|gvk|kvk|kdv|otv   # vergi kanunları
    )\s*\d+                   # madde numarası
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Konuşma dili belirteçleri — HyDE için yüksek sinyal
_CONVERSATIONAL_RE = re.compile(
    r"""
    ne\s+yapabilirim|ne\s+yapmalıyım|nasıl\s+çözebilirim|
    hakkım\s+var\s+mı|yapabilir\s+miyim|mümkün\s+mü|
    nasıl\s+şikâyet|nereye\s+başvur|ne\s+hakkım|
    benden\s+ne\s+ister|ne\s+kadar\s+sürer
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _query_complexity(question: str) -> float:
    """0–1 arası sorgu karmaşıklık puanı.

    Düşük (0.0–0.3): spesifik / kanun referanslı / çok kısa → genişletme gerekmez.
    Orta  (0.4–0.6): standart soru → seçici genişletme.
    Yüksek (0.7–1.0): konuşma dili / belirsiz / uzun → genişletme yardımcı.
    """
    words = question.strip().split()
    n = len(words)

    # Kanun/madde referansı → zaten spesifik, embedding boşluğu yok
    if _LAW_REF_RE.search(question):
        return 0.15

    # Çok kısa (1-4 kelime): muhtemelen anahtar kelime, HyDE overkill
    if n <= 4:
        return 0.2

    # Konuşma dili kalıpları → vatandaş dili köprüsü gerekli, HyDE için ideal
    if _CONVERSATIONAL_RE.search(question):
        return 0.85

    # Uzun soru (12+ kelime): ayrıntılı senaryo anlatımı → genişletme faydalı
    if n >= 12:
        return 0.75

    # 5-11 kelime: orta karmaşıklık
    return 0.5


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Bir sorgu için retrieval strateji kararı."""

    use_hyde: bool
    use_mq: bool
    strategy: str       # "hybrid" | "hyde" | "mq" | "hyde+mq"
    complexity: float
    domain: str


def route_query(question: str, domain: str) -> RoutingDecision:
    """Sorgu ve domain için HyDE/MQ kullanım kararını ver.

    ADAPTIVE_ROUTING_ENABLED=0 ise eski global flag davranışına döner.
    """
    complexity = _query_complexity(question)

    if not ADAPTIVE_ROUTING_ENABLED:
        # Eski davranış: global flag'ler direkt kullanılır, routing yok
        use_hyde = HYDE_ENABLED
        use_mq = MULTI_QUERY_ENABLED
    else:
        use_hyde = (
            HYDE_ENABLED
            and domain in HYDE_ENABLED_DOMAINS
            and complexity >= QUERY_COMPLEXITY_THRESHOLD
        )
        use_mq = (
            MULTI_QUERY_ENABLED
            and domain in MULTI_QUERY_ENABLED_DOMAINS
            and complexity >= QUERY_COMPLEXITY_THRESHOLD
        )

    if use_hyde and use_mq:
        strategy = "hyde+mq"
    elif use_hyde:
        strategy = "hyde"
    elif use_mq:
        strategy = "mq"
    else:
        strategy = "hybrid"

    decision = RoutingDecision(
        use_hyde=use_hyde,
        use_mq=use_mq,
        strategy=strategy,
        complexity=complexity,
        domain=domain,
    )
    log.debug(
        "adaptive_router_decision",
        domain=domain,
        strategy=strategy,
        complexity=round(complexity, 2),
        n_words=len(question.split()),
    )
    return decision
