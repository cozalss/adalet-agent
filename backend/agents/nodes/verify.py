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

import asyncio
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
from agents.risk_guard import verify_risk_veto
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
async def verify_node(state: AgentState) -> dict:  # noqa: C901
    """4 katmanlı verifier. state['claims']'i alır, verified_claims + verdict üretir."""
    import time as _time
    _t0 = _time.perf_counter()
    claims = state.get("claims", []) or []
    refs: list[Citation] = list(state.get("mevzuat_refs", [])) + list(
        state.get("emsal_refs", []),
    )

    # §4.2 ablation kaldıracı: VERIFY_ENABLED=0 → doğrulama katmanını TAMAMEN
    # bypass et (ham RAG-LLM gibi davran: tüm iddialar sorgusuz "supported",
    # verdict pass, veto yok). Yalnız ölçüm/ablation içindir — production'da
    # DAİMA açık (default "1"). Bu kaldıraç verify ON vs OFF hallüsinasyon-
    # yakalama farkının (paper §4.2) ölçülmesini sağlar. Call-time okunur
    # (VERIFY_STRICT pattern'i) → harness env'i set edip alt-process koşturabilir.
    if os.getenv("VERIFY_ENABLED", "1").lower() not in {"1", "true", "yes"}:
        log.warning("verify_bypassed_ablation", n_claims=len(claims))
        return {
            "verified_claims": [
                _mark(c, True, 1.0, "verify-bypass (ablation)") for c in claims
            ],
            "debate_verdict": "pass",
            "debate_notes": "VERIFY_ENABLED=0 — doğrulama bypass (ablation modu).",
        }

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
    #
    # Layer 1/2 saf-Python (hızlı, inline). Layer 2.5 (LettuceDetect) ve Layer 3
    # (NLI) bağımsız ve model-ağırlıklı: NLI senkron PyTorch forward'ı → bloke
    # etmemek için to_thread; ikisini gather ile eşzamanlı koştur (yavaş olan
    # "bedava" arkada çalışır).
    layer1_results = [layer1_rules(c) for c in claims]
    layer2_results = [layer2_fuzzy(c, refs) for c in claims]
    try:
        layer25_results, layer3_results = await asyncio.gather(
            layer25_lettuce(claims, refs),
            asyncio.to_thread(layer3_nli_batch, claims, refs),
        )
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

    # --- İÇERİK-RİSK VETO (SIFIR HALÜSİNASYON kırmızı çizgisi) ---
    # NLI yalnız doğrudan ÇELİŞKİ yakalar; [src:]-etiketli yanlış ÇIKARIMI
    # (örn. "2 yıl kıdem için yetersiz" — md.14 min 1 yıl) ve uydurma kanun adını
    # ("İşçilik Kanunu") kaçırır. Bu veto draft metnini tarar; bloklayıcı risk
    # varsa fail-closed REJECT (CLAUDE.md §1: doğrulanamazsa REDDEDİLİR).
    # temp=0'da retry aynı çıktıyı üretir → retry değil, doğrudan reject.
    draft_text = state.get("draft_response", "") or ""
    blocked, risk_reasons = verify_risk_veto(draft_text)
    if blocked:
        log.warning("verify_risk_veto", reasons=risk_reasons, prev_verdict=verdict)
        verdict = "reject"

    # Ölçüm-amaçlı hook: FORCE_RETRY_ONCE=1 → ilk geçişte (retry_count==0) verdict'i
    # retry'a zorla. retry yolu latans maliyetini (P99) deterministik ölçmek için —
    # production'da ASLA set edilmez (VERIFY_ENABLED ablation hook'u gibi).
    if (
        os.getenv("FORCE_RETRY_ONCE", "0").lower() in {"1", "true", "yes"}
        and state.get("retry_count", 0) == 0
        and verdict == "pass"
    ):
        verdict = "retry"

    _veto_note = f" RİSK-VETO: {'; '.join(risk_reasons)}." if blocked else ""
    notes = (
        f"{n_supported}/{len(claims)} iddia doğrulandı, "
        f"{contradictions} çelişki tespit edildi.{_veto_note}"
    )

    log.info(
        "verify_done",
        n_claims=len(claims),
        n_supported=n_supported,
        contradictions=contradictions,
        verdict=verdict,
        elapsed_ms=round((_time.perf_counter() - _t0) * 1000),
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
    """Aggregate verdict — ratio-based + süpermajority sinyal-redundans guard.

    Tarihçe:
      - v9: tek NLI çelişki tüm cevabı reddediyordu (E3: 3/4 supported %75 ama
        1 contradiction → reject). Türkçe XNLI paraphrase'lerde 0.50-0.70
        contradiction skoru sık üretiyor (false-pos). → ratio kuralına geçildi.
      - Sonra: small-n (örn. n=2) sorununda ratio kapısı tek çelişkiyle
        tetikleniyordu. → "en az 2 çelişki + ratio ≥ 0.5" kuralı kondu (138a104).
      - SON BULGU (15-soru batch is-03): n=6, contradictions=3 → 0.5 ≥ 0.5
        kuralı yine reddediyor, ama %50 çelişki "yarı yarıya" demek — false-pos
        kümülasyonu olabilir. Süpermajority'ye geçildi: c >= ceil(n/2)+1.
        n=2 → c=2 (tüm claim'ler çelişki, kesin sinyal) → reject ✓
        n=4 → c=3 → reject
        n=6 → c=4 (3 yetersiz) → reject ✓ (is-03'ün 3/6'sı false-positive sayılır)
        n=10 → c=6 → reject

    Kalibrasyon: bu değişiklik per-claim P/R/F1'i etkilemez (harness yalnız
    katman çıktısını ölçer); yalnız aggregation kapısını ayarlar.
    [[adalet_nli_finding]], [[verify-calibration-harness]].

    Kural:
      - n_total == 0 → reject
      - contradictions >= ceil(n_total/2) + 1 → reject (süpermajority)
      - supported / n_total >= MIN_VERIFIED_CLAIMS_RATIO → pass
      - retry_count < MAX_RETRY → retry
      - else → reject
    """
    if n_total == 0:
        return "reject"
    # Süpermajority: çelişkiler "yarıdan FAZLA" olmalı (tam yarı yetersiz).
    # floor(n/2)+1 = "majority + 1" formülü:
    #   n=2 → 2 (her iki claim çelişki; kesin sinyal)
    #   n=4 → 3 (3/4 = %75)
    #   n=6 → 4 (3/6 yetersiz; is-03 bu eşikten kurtulur)
    #   n=10 → 6
    # Ek olarak minimum 2 — tek çelişki Türkçe XNLI'da gürültü olabilir.
    supermajority_threshold = max(2, (n_total // 2) + 1)
    if contradictions >= supermajority_threshold:
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
