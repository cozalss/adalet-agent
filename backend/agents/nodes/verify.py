"""Verify ajanı — 4 katmanlı claim doğrulama (sıfır halüsinasyon kapısı).

Sprint-4 W4.1: katman fonksiyonları `agents/verifier_layers.py`'ye taşındı.
Bu modül artık SADECE orkestra + verdict aggregation + claim marking içerir.

Her LLM iddiası şu katmanları geçer:

  Katman 1 — Rules: Madde-no regex syntactic geçerlilik (TKHK m.11 gibi)
  Katman 2 — Fuzzy: rapidfuzz pozitif eşleşme (>= FUZZY_SUPPORT_THRESHOLD)
  Katman 2.5 — LettuceDetect token-level grounding
  Katman 3 — NLI: mDeBERTa XNLI contradiction veto
  Katman 4 — RARR (W4.2): evidence augmentation (opt-in, RARR_ENABLED=1)

Veredict aggregation:
  - %50+ claim doğrulanmış AND hiç contradiction yok → "pass"
  - %50- doğrulanmış AND retry hakkı var          → "retry"
  - Contradiction VAR (NLI veto)                  → "reject"

Notlar:
- NLI [[adalet_nli_finding]] memorisine uygun: SADECE contradiction veto.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

import structlog

from agents.config import (
    FUZZY_SUPPORT_THRESHOLD,
    LETTUCE_SUPPORT_THRESHOLD,
    LETTUCE_VETO_THRESHOLD,
    MAX_RETRY,
    MIN_VERIFIED_CLAIMS_RATIO,
    NLI_ENTAILMENT_THRESHOLD,
)
from agents.state import AgentState, Citation, Claim, DebateVerdict
from agents.verifier_layers import (
    VerifierUnavailableError,
    layer1_rules,
    layer2_fuzzy,
    layer3_nli_batch,
    layer25_lettuce,
)
from core.observability import observe_node

# Sprint-4 W4.1: backward-compat re-export — eski test'ler private isimlerle
# import ediyor. Modül split sonrası verifier_layers.py public isimlere alias.
_layer1_rules = layer1_rules
_layer2_fuzzy = layer2_fuzzy
_layer3_nli_batch = layer3_nli_batch
_layer25_lettuce = layer25_lettuce

log = structlog.get_logger()

# Sprint-4 W4.2: RARR-lite 4. katman (opt-in).
RARR_ENABLED = os.getenv("RARR_ENABLED", "0").lower() in {"1", "true", "yes"}


@observe_node(name="verify")
async def verify_node(state: AgentState) -> dict:
    """4 katmanlı verifier. state['claims']'i alır, verified_claims + verdict üretir."""
    claims = state.get("claims", []) or []
    refs: list[Citation] = list(state.get("mevzuat_refs", [])) + list(
        state.get("emsal_refs", []),
    )

    if not claims:
        log.warning("verify_no_claims")
        return {
            "verified_claims": [],
            "debate_verdict": _verdict_from_ratio(0, 0, state),
            "debate_notes": "Cevapta doğrulanabilir iddia bulunamadı.",
        }

    if not refs:
        log.warning("verify_no_refs", n_claims=len(claims))
        return {
            "verified_claims": [_mark_unverified(c, "Kaynak yok") for c in claims],
            "debate_verdict": "reject",
            "debate_notes": "Retrieval kaynak getirmedi; iddialar doğrulanamadı.",
        }

    # --- Katman çağrıları (paralel-safe, side-effect yok) ---
    # VERIFY_STRICT modunda NLI/Lettuce çökerse VerifierUnavailableError fırlar →
    # fail-closed reject. Doğrulayıcı çalışmadıysa hiçbir iddia "doğrulanmış"
    # sayılamaz (SIFIR HALÜSİNASYON, CLAUDE.md §1).
    try:
        layer1_results = [layer1_rules(c) for c in claims]
        layer2_results = [layer2_fuzzy(c, refs) for c in claims]
        layer25_results = await layer25_lettuce(claims, refs)
        layer3_results = layer3_nli_batch(claims, refs)
    except VerifierUnavailableError as exc:
        log.error("verify_fail_closed", error=str(exc), n_claims=len(claims))
        return {
            "verified_claims": [
                _mark_unverified(c, "Doğrulayıcı kullanılamadı") for c in claims
            ],
            "debate_verdict": "reject",
            "debate_notes": (
                "Doğrulama sistemi kullanılamadı; cevap güvenlik gereği "
                f"reddedildi: {exc}"
            ),
        }

    # Katman 4 (RARR): claim için ek evidence; opt-in
    if RARR_ENABLED:
        try:
            from verifier.rarr import augment_evidence_batch
            await augment_evidence_batch(claims, refs)
            log.info("rarr_layer_invoked", n_claims=len(claims))
        except ImportError:
            log.debug("rarr_module_missing")

    # --- Aggregate per claim ---
    verified: list[Claim] = []
    contradictions = 0
    n_supported = 0

    for i, claim in enumerate(claims):
        l1_ok, l1_msg = layer1_results[i]
        l2_score, l2_msg, _l2_best_idx = layer2_results[i]
        l25_score, l25_fallback = layer25_results[i]
        l3_contradicted, l3_ent, l3_con, l3_msg = layer3_results[i]

        # NLI hard veto — claim kaynakla çelişiyor
        if l3_contradicted:
            verified.append(_mark(claim, False, l3_con, f"NLI veto: {l3_msg}"))
            contradictions += 1
            continue

        # LettuceDetect soft veto — token-level grounding çok düşük
        if not l25_fallback and l25_score < LETTUCE_VETO_THRESHOLD:
            verified.append(
                _mark(claim, False, l25_score, f"LettuceDetect veto {l25_score:.2f}"),
            )
            contradictions += 1
            continue

        # Rules failed → unverified
        if not l1_ok:
            verified.append(_mark(claim, False, 0.0, f"Format: {l1_msg}"))
            continue

        # Fuzzy positive
        if l2_score >= FUZZY_SUPPORT_THRESHOLD:
            verified.append(_mark(claim, True, l2_score, f"Fuzzy {l2_score:.2f}: {l2_msg}"))
            n_supported += 1
            continue

        # LettuceDetect positive
        if not l25_fallback and l25_score >= LETTUCE_SUPPORT_THRESHOLD:
            verified.append(_mark(claim, True, l25_score, f"Lettuce {l25_score:.2f}"))
            n_supported += 1
            continue

        # NLI entailment fallback
        if l3_ent >= NLI_ENTAILMENT_THRESHOLD:
            verified.append(_mark(claim, True, l3_ent, f"NLI entail {l3_ent:.2f}"))
            n_supported += 1
            continue

        # Hiçbiri yok → unsupported
        best = max(l2_score, l25_score, l3_ent)
        verified.append(_mark(claim, False, best, f"Yetersiz kanıt (best={best:.2f})"))

    verdict = _verdict_from_ratio(n_supported, len(claims), state, contradictions)
    notes = (
        f"{n_supported}/{len(claims)} iddia doğrulandı, "
        f"{contradictions} çelişki tespit edildi."
    )

    log.info(
        "verify_done",
        n_claims=len(claims),
        n_supported=n_supported,
        contradictions=contradictions,
        verdict=verdict,
    )

    return {
        "verified_claims": verified,
        "debate_verdict": verdict,
        "debate_notes": notes,
    }


# --------------------------------------------------------------------------
#  Verdict aggregation
# --------------------------------------------------------------------------

def _verdict_from_ratio(
    n_supported: int,
    n_total: int,
    state: AgentState,
    contradictions: int = 0,
) -> DebateVerdict:
    """Aggregate verdict — ratio-based, NLI tek-claim veto kaldırıldı.

    v9 ölçümünde bulgu: tek NLI contradiction tüm cevabı reddediyordu
    (E3: 3/4 supported %75 ama 1 contradiction → reject). Türkçe XNLI
    paraphrase'lerde 0.50-0.70 contradiction skoru sık üretiyor (false-pos).

    Yeni kural:
      - n_total == 0 → reject
      - contradictions / n_total >= 0.5 → reject (çoğu çelişkili)
      - supported / n_total >= MIN_VERIFIED_CLAIMS_RATIO → pass
      - retry_count < MAX_RETRY → retry
      - else → reject

    [[adalet_nli_finding]] memory ile uyumlu.
    """
    if n_total == 0:
        return "reject"
    contradiction_ratio = contradictions / n_total
    if contradiction_ratio >= 0.5:
        return "reject"
    ratio = n_supported / n_total
    if ratio >= MIN_VERIFIED_CLAIMS_RATIO:
        return "pass"
    if state.get("retry_count", 0) < MAX_RETRY:
        return "retry"
    return "reject"


def _mark(
    claim: Claim,
    verified: bool,
    score: float,
    reason: str,
) -> Claim:
    """Claim'i verified/score/reason ile etiketle (immutable update)."""
    return Claim(
        text=claim["text"],
        cite_ids=claim.get("cite_ids", []),
        verified=verified,
        verify_score=float(score),
        verify_reason=reason,
    )


def _mark_unverified(claim: Claim, reason: str) -> Claim:
    return _mark(claim, False, 0.0, reason)


__all__: Iterable[str] = ("verify_node",)
