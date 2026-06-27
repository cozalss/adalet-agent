"""Query decomposition — karmaşık çok-parçalı soruyu bağımsız alt-sorulara böl (multi-hop agentic RAG).

Sorun: "2 yıldır çalışıyorum, kıdem + ihbar + fazla mesai + yıllık izin alabilir miyim?" tek
embedding'le retrieve edilince her parça iyi kapsanmaz (vektör çok-konuyu ortalar → bazı talepler
zayıf kaynak alır). Çözüm: bağımsız alt-sorulara böl → mevzuat node her birine AYRI retrieve edip
birleştirir → her hukuki talep güçlü kaynak alır. Referans: agentic RAG query planning (LangGraph 2026).

Akış: triaj → decompose (DECOMPOSE_ENABLED) → [mevzuat, emsal] (sub_questions'ı kullanır) → draft.
Default-safe: DECOMPOSE_ENABLED=0 → no-op (sub_questions boş → mevzuat tek-atış davranır).
Tek-parça soruda da no-op (LLM 0-1 alt-soru döner → ek retrieval yok, latency eklenmez).
"""
from __future__ import annotations

import json
import os
import re

import structlog

from agents.llm import ChatMessage, get_llm
from agents.state import AgentState
from core.observability import observe_node

log = structlog.get_logger()

DECOMPOSE_ENABLED = os.getenv("DECOMPOSE_ENABLED", "0").lower() in {"1", "true", "yes"}
MAX_SUB_QUESTIONS = int(os.getenv("DECOMPOSE_MAX_SUB", "4"))
_MIN_QUESTION_CHARS = 40  # kısa/basit soru → bölme gereksiz
_MAX_TOKENS = 240

_SYSTEM = (
    "Türk hukuk asistanısın. Vatandaşın sorusunu BAĞIMSIZ alt-hukuki-taleplere böl. "
    "Soru TEK bir konu içeriyorsa (örn 'kira artış oranı nedir', 'depozito kaç aylık') BOŞ liste dön. "
    "ÇOK-PARÇALIYSA (örn 'kıdem + ihbar + fazla mesai + yıllık izin alabilir miyim') her BAĞIMSIZ "
    "talebi ayrı, retrieve edilebilir KISA alt-soruya çevir (örn 'kıdem tazminatı şartları', "
    "'ihbar tazminatı süresi', 'fazla mesai ücreti hesabı'). Alt-sorular Türkçe, net, tek-konu, en "
    "fazla 4 tane. Soruda OLMAYAN talep EKLEME (uydurma yok). "
    'Yalnız JSON: {"sub_questions": ["...", "..."]}'
)


def _sanitize_sub(s: str) -> str:
    """LLM çıktısı alt-soruyu retrieval/draft prompt'una enjekte etmeden temizle (prompt-injection
    savunması, derinlik): tek-satır, kontrol-char/markdown/liste-işareti soyulur, tavan 160."""
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s)        # kontrol karakterleri (yeni-satır dahil) → boşluk
    s = re.sub(r"\s+", " ", s).strip()
    s = s.lstrip("#*->`•·.) ").strip()            # markdown/liste başı
    return s[:160]


@observe_node(name="decompose")
async def decompose_node(state: AgentState) -> dict[str, object]:
    """Çok-parçalı soruyu alt-sorulara böl → state['sub_questions']. Tek-parça/basit → no-op."""
    if not DECOMPOSE_ENABLED:
        return {}
    question = (state.get("question") or "").strip()
    domain = state.get("domain", "unknown")
    # Basit/kısa/kapsam-dışı → bölme (gereksiz LLM çağrısı + latency).
    if domain == "unknown" or len(question) < _MIN_QUESTION_CHARS:
        return {}
    # Ucuz ön-filtre: çok-parça İŞARETİ yok + kısa → LLM ÇAĞIRMA (tek-konu sorularda latency
    # eklemez; gerçek çok-parçalılar bağlaç/liste/+ içerir). "kıdem alabilir miyim" gibi tek-talep
    # geçmez; "kıdem ve ihbar ve fazla mesai" geçer.
    _ql = question.lower()
    has_signal = any(s in _ql for s in (" ve ", " ile ", " ayrıca ", " hem ", ",", "+", " ya da ", " veya "))
    if not has_signal and len(question) < 90:
        return {}

    try:
        llm = get_llm()
        resp = await llm.chat(
            messages=[
                ChatMessage(role="system", content=_SYSTEM),
                ChatMessage(role="user", content=question),
            ],
            temperature=0.0,
            max_tokens=_MAX_TOKENS,
            json_mode=True,
        )
        data = json.loads(resp.content or "{}")
        raw = data.get("sub_questions") if isinstance(data, dict) else None
        subs = [
            cleaned for s in (raw or [])
            if isinstance(s, str) and (cleaned := _sanitize_sub(s)) and 5 <= len(cleaned) <= 160
        ]
    except Exception as exc:  # LLM/parse hatası → no-op (tek-atış retrieval'a düş)
        log.warning("decompose_failed", error=type(exc).__name__)
        return {}

    # 0-1 alt-soru → tek-parça; ek retrieval gereksiz (mevcut davranış korunur).
    if len(subs) < 2:
        log.info("decompose_single", n=len(subs))
        return {}

    # Dedup (sıra korunur) + tavan.
    seen: set[str] = set()
    uniq: list[str] = []
    for s in subs:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    uniq = uniq[:MAX_SUB_QUESTIONS]
    log.info("decompose_done", n=len(uniq))
    return {"sub_questions": uniq}


__all__ = ("DECOMPOSE_ENABLED", "decompose_node")
