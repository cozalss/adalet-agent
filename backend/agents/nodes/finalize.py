"""Finalize ajanı — son cevabı topla, disclaimer ekle, güven skorunu hesapla.

E2E baseline akış için verify/debate atlanabilir; bu node tek başına da çalışır.
"""

from __future__ import annotations

import re

import structlog

from agents.config import DISCLAIMER_TR
from agents.state import AgentState
from core.observability import observe_node

log = structlog.get_logger()

# Cümle ayraç + kaynak etiketi — draft.py ile aynı desen (claim extraction'la tutarlı).
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ])")
_SRC_TAG_RE = re.compile(r"\[src:\s*[A-Za-z0-9_\-]+\s*\]")


@observe_node(name="finalize")
async def finalize_node(state: AgentState) -> dict:
    domain = state.get("domain", "unknown")
    verdict = state.get("debate_verdict", "pass")

    # Reddedildi → boilerplate avukat tavsiyesi
    if domain == "unknown" or verdict != "pass":
        return _reject_response(state)

    draft = state.get("draft_response", "").strip()
    verified_claims = state.get("verified_claims", []) or state.get("claims", [])

    if not draft:
        return _reject_response(state)

    n_claims = len(state.get("claims", []) or [])
    n_verified = len([c for c in verified_claims if c.get("verified", False)])

    # İddia VAR ama hiçbiri doğrulanmadı → gösterilecek güvenli içerik yok, reddet.
    if n_claims > 0 and n_verified == 0:
        return _reject_response(state, _unverified_claims_reason(verified_claims))

    # Fail-closed ama kapsam-koruyan: doğrulanmamış iddiaların cümlelerini taslaktan
    # ÇIKAR, doğrulanmış içeriği göster. Halüsinasyon kullanıcıya gitmez (CLAUDE.md §1)
    # ama tüm cevabı reddetmeyiz — vatandaş doğrulanmış kısımdan yararlanır.
    filtered_draft, n_dropped = _filter_to_verified(draft, verified_claims)
    if not filtered_draft.strip():
        return _reject_response(state, _unverified_claims_reason(verified_claims))

    # Citation bloğu
    citations_md = _format_citations(state)
    final = f"{filtered_draft}\n\n---\n**Kaynaklar:**\n{citations_md}\n\n{DISCLAIMER_TR}"

    confidence = _compute_confidence(state, verified_claims)

    log.info(
        "finalize_done",
        confidence=confidence, n_claims=len(verified_claims), dropped=n_dropped,
    )
    return {
        "response": final,
        "confidence": confidence,
        "disclaimers": [DISCLAIMER_TR],
        # Tahmin (8. ajan) hesapladıysa state'te var; pass cevapta gösterilir.
        "prediction": state.get("prediction"),
    }


def _normalize_sentence(text: str) -> str:
    """Karşılaştırma için normalize: kaynak etiketini sil, boşlukları sıkıştır, küçült."""
    return " ".join(_SRC_TAG_RE.sub("", text).split()).lower()


def _filter_to_verified(draft: str, verified: list) -> tuple[str, int]:
    """Doğrulanmamış claim'lere karşılık gelen cümleleri taslaktan çıkar.

    claim["text"] (draft cümlesinden çıkarılmıştı) ile draft cümleleri normalize
    edilip eşleştirilir. Bir cümle doğrulanmamış bir claim'le eşleşiyor AMA aynı
    zamanda doğrulanmış bir claim'le eşleşmiyorsa atılır. İddia olmayan cümleler
    (giriş, disclaimer) ve doğrulanmış cümleler korunur.

    Returns:
        (filtrelenmiş taslak, atılan cümle sayısı)
    """
    unverified = [
        _normalize_sentence(c["text"]) for c in verified if not c.get("verified", False)
    ]
    unverified = [u for u in unverified if u]
    if not unverified:
        return draft, 0
    verified_txt = [
        _normalize_sentence(c["text"]) for c in verified if c.get("verified", False)
    ]
    verified_txt = [v for v in verified_txt if v]

    kept: list[str] = []
    dropped = 0
    for sent in _SENT_SPLIT_RE.split(draft):
        norm = _normalize_sentence(sent)
        if not norm:
            kept.append(sent)
            continue
        is_unverified = any(u in norm or norm in u for u in unverified)
        is_verified = any(v in norm or norm in v for v in verified_txt)
        if is_unverified and not is_verified:
            dropped += 1
            continue
        kept.append(sent)
    return " ".join(s.strip() for s in kept if s.strip()).strip(), dropped


def _reject_response(state: AgentState, reason: str | None = None) -> dict:
    reason = reason or state.get("debate_notes") or state.get("triage_reasoning") or ""
    body = (
        "Bu soruya doğrulanmış kaynaklarla yanıt veremedim. "
        "Lütfen bir avukata danışın.\n\n"
        f"Detay: {reason}"
    )
    return {
        "response": f"{body}\n\n{DISCLAIMER_TR}",
        "confidence": 0.0,
        "disclaimers": [DISCLAIMER_TR],
        # Reddedilen/kapsam-dışı cevapta kazanma tahmini gösterme (yanıltıcı olur).
        "prediction": None,
        "debate_verdict": "reject",
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


def _unverified_claims_reason(verified: list) -> str:
    n_total = len(verified)
    n_unverified = len([c for c in verified if not c.get("verified", False)])
    first_reason = next(
        (str(c.get("verify_reason", "")) for c in verified if not c.get("verified", False)),
        "",
    )
    detail = f"{n_unverified}/{n_total} iddia doğrulanamadı."
    return f"{detail} İlk neden: {first_reason}" if first_reason else detail
