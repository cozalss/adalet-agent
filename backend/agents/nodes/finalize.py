"""Finalize ajanı — son cevabı topla, disclaimer ekle, güven skorunu hesapla.

E2E baseline akış için verify/debate atlanabilir; bu node tek başına da çalışır.
"""

from __future__ import annotations

import structlog

from agents.config import DISCLAIMER_TR
from agents.state import AgentState
from core.observability import observe_node

log = structlog.get_logger()


@observe_node(name="finalize")
async def finalize_node(state: AgentState) -> dict:
    domain = state.get("domain", "unknown")
    verdict = state.get("debate_verdict", "pass")

    # Reddedildi → boilerplate avukat tavsiyesi
    if domain == "unknown" or verdict == "reject":
        return _reject_response(state)

    draft = state.get("draft_response", "").strip()
    verified_claims = state.get("verified_claims", []) or state.get("claims", [])

    if not draft:
        return _reject_response(state)

    # Citation bloğu
    citations_md = _format_citations(state)
    final = f"{draft}\n\n---\n**Kaynaklar:**\n{citations_md}\n\n{DISCLAIMER_TR}"

    confidence = _compute_confidence(state, verified_claims)

    log.info("finalize_done", confidence=confidence, n_claims=len(verified_claims))
    return {
        "response": final,
        "confidence": confidence,
        "disclaimers": [DISCLAIMER_TR],
    }


def _reject_response(state: AgentState) -> dict:
    reason = state.get("triage_reasoning") or state.get("debate_notes") or ""
    body = (
        "Bu soruya doğrulanmış kaynaklarla yanıt veremedim. "
        "Lütfen bir avukata danışın.\n\n"
        f"Detay: {reason}"
    )
    return {
        "response": f"{body}\n\n{DISCLAIMER_TR}",
        "confidence": 0.0,
        "disclaimers": [DISCLAIMER_TR],
    }


def _format_citations(state: AgentState) -> str:
    refs = []
    for r in state.get("mevzuat_refs", []):
        refs.append(f"- [Mevzuat] {r['title']} ({r['url']})")
    for r in state.get("emsal_refs", []):
        refs.append(f"- [Emsal] {r['title']} ({r['url']})")
    return "\n".join(refs) if refs else "(kaynak bulunamadı)"


def _compute_confidence(state: AgentState, verified: list) -> float:
    """Basit harman: domain güveni + doğrulanmış claim oranı + retrieval kalitesi."""
    dom_conf = state.get("domain_confidence", 0.0)
    n_claims = len(state.get("claims", []) or [])
    # Fail-closed: "verified" anahtarı yoksa (doğrulama atlanmış/eksik) iddiayı
    # doğrulanmamış say. Güven skorunu şişirmemek için varsayılan False.
    n_ver = len([c for c in verified if c.get("verified", False)])
    claim_ratio = (n_ver / n_claims) if n_claims else 1.0

    refs = (state.get("mevzuat_refs") or []) + (state.get("emsal_refs") or [])
    retrieval_score = min(1.0, sum(r["score"] for r in refs[:5]) / 5.0) if refs else 0.0

    return round(0.4 * dom_conf + 0.4 * claim_ratio + 0.2 * retrieval_score, 3)
