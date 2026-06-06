"""Debate ajanı — Constitutional AI self-critique + retry karar verici.

Verifier (verify_node) bir verdict üretti: pass / retry / reject.
Debate ajanı bu verdict'i KABUL eder ama ek bir LLM kritiği yapar:

  pass    → LLM revise/polish opsiyonel (küçük rötuş)
  retry   → LLM "ne eksik" özetle; retry_count++ ile draft'a geri dön
  reject  → kullanıcıya "avukata danışın" yanıtı hazırla

LLM JSON çıktısı:
  {"verdict": "...", "score": 0.0-1.0, "issues": [...],
   "revised_answer": "..." | null, "rationale": "..."}

Eğer LLM cevabı bozuksa veya verify_node zaten reject demişse, ekstra LLM
çağırmadan deterministic karara düş. Hızlı + güvenli.

Mock mode'da JSON parse hatasını gracefully handle eder; çağırılan node
verify_node verdict'ine güvenir.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import structlog

from agents.config import (
    DEBATE_MAX_TOKENS,
    DEBATE_REJECT_THRESHOLD,
    LLM_TEMPERATURE,
    MAX_RETRY,
)
from agents.llm import ChatMessage, get_llm
from agents.state import AgentState, Citation, DebateVerdict
from core.observability import observe_node

log = structlog.get_logger()

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "debate.tr.txt"


@observe_node(as_type="generation", name="debate")
async def debate_node(state: AgentState) -> dict:
    """Verify sonrası hakemlik — verdict'i kabul/iyileştir, retry sayacını yönet."""
    base_verdict: DebateVerdict = state.get("debate_verdict", "pass")

    # Hard reject veya verify hiç claim doğrulayamadıysa → ekstra LLM yok
    if base_verdict == "reject":
        return _final(state, "reject", _build_reject_notes(state))

    # Pass durumunda taslak zaten iyi; LLM rötuşu opsiyonel
    # Token tasarrufu için pass'i extra LLM olmadan onaylıyoruz.
    if base_verdict == "pass":
        return _final(state, "pass", "Verifier onayladı; debate ek kritik gerektirmiyor.")

    # base_verdict == "retry" → LLM'e sor, gerçekten retry mi yoksa reject mi?
    retry_count = state.get("retry_count", 0)

    if retry_count >= MAX_RETRY:
        # Retry limiti doldu → reject
        return _final(
            state,
            "reject",
            f"Retry limiti ({MAX_RETRY}) doldu; doğrulanmış cevap üretilemedi.",
        )

    # Ölçüm-amaçlı hook: FORCE_RETRY_ONCE=1 → ilk geçişte gerçek retry loop'unu
    # zorla (mevzuat+emsal+draft+verify 2x). Retry P99 maliyetini deterministik
    # ölçmek için — production'da ASLA set edilmez. verify.py'deki kardeş hook ile
    # birlikte: verify "retry" der, debate burada loop'u garanti eder.
    import os
    if os.getenv("FORCE_RETRY_ONCE", "0").lower() in {"1", "true", "yes"} and retry_count == 0:
        return _final(state, "retry", "FORCE_RETRY_ONCE — ölçüm retry loop'u",
                      increment_retry=True)

    if not _retry_llm_enabled():
        verified = state.get("verified_claims") or []
        if any(c.get("verified", False) for c in verified):
            return _final(
                state,
                "pass",
                "Verifier kısmi destek buldu; hızlı modda yalnız doğrulanmış kısım döndürülür.",
            )
        # 0 doğrulanmış claim → reddetmeden ÖNCE bir kez deterministik retry (re-retrieve +
        # re-draft). Draft GPU-non-determinism nedeniyle aynı soru bazen ground bazen 0/0
        # veriyordu (ölçüldü iter13-14); 2. draft genelde ground'lar → SAHTE reject'ler
        # grounded cevaba döner. Yalnız ilk geçişte (retry_count==0) → +1 pass yalnız
        # would-be-reject'lerde (iyi/kısmi cevaplar üstte zaten döndü). 2. geçiş hâlâ 0 →
        # gerçek reject (MAX_RETRY guard'ı da var). LLM debate KAPALI olsa da geçerli (re-draft).
        if retry_count == 0:
            return _final(
                state,
                "retry",
                "0 doğrulanmış claim — bir kez yeniden üret (draft non-determinism telafisi).",
                increment_retry=True,
            )
        return _final(
            state,
            "reject",
            "Verifier yeterli destek bulamadı (yeniden üretim sonrası da doğrulanamadı).",
        )

    # LLM debate çağrısı
    try:
        debate_result = await _llm_critique(state)
    except Exception as exc:
        log.warning("debate_llm_failed", error=str(exc))
        # Fallback: deterministic retry (verify zaten retry demiş)
        return _final(
            state,
            "retry",
            f"LLM kritik hata, deterministic retry: {exc!s}",
            increment_retry=True,
        )

    llm_verdict = _coerce_verdict(debate_result.get("verdict", "retry"))
    score = _coerce_score(debate_result.get("score", 0.5))
    issues = debate_result.get("issues", []) or []
    rationale = str(debate_result.get("rationale", ""))

    # Eşik altı skor → hard reject
    if score < DEBATE_REJECT_THRESHOLD:
        llm_verdict = "reject"

    notes = _format_notes(llm_verdict, score, issues, rationale)
    log.info("debate_done", verdict=llm_verdict, score=score, retry=retry_count)

    return _final(
        state,
        llm_verdict,
        notes,
        increment_retry=(llm_verdict == "retry"),
    )


# --------------------------------------------------------------------------
#  LLM call
# --------------------------------------------------------------------------

def _retry_llm_enabled() -> bool:
    """Retry verdict'inde pahalı LLM debate/retry döngüsünü aç/kapat."""
    return os.getenv("DEBATE_LLM_ON_RETRY", "0").lower() in {"1", "true", "yes"}


async def _llm_critique(state: AgentState) -> dict:
    """LLM'e JSON-mode debate prompt'u gönder, JSON parse et."""
    prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    user_payload = _build_user_payload(state)
    llm = get_llm()
    resp = await llm.chat(
        messages=[
            ChatMessage(role="system", content=prompt),
            ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
        ],
        temperature=LLM_TEMPERATURE,
        max_tokens=DEBATE_MAX_TOKENS,
        json_mode=True,
    )
    return _parse_debate_json(resp.content)


def _build_user_payload(state: AgentState) -> dict:
    """Debate LLM'e verilecek input JSON'u."""
    refs: list[Citation] = list(state.get("mevzuat_refs", [])) + list(
        state.get("emsal_refs", []),
    )
    verify_report = [
        {
            "claim": c["text"],
            "verified": c.get("verified", False),
            "score": c.get("verify_score", 0.0),
            "reason": c.get("verify_reason", ""),
        }
        for c in state.get("verified_claims", []) or state.get("claims", [])
    ]
    return {
        "soru": state.get("question", ""),
        "domain": state.get("domain", "unknown"),
        "taslak": state.get("draft_response", ""),
        "kaynaklar": [
            {
                "id": r["source_id"],
                "title": r["title"],
                "snippet": r["snippet"][:400],
            }
            for r in refs[:10]  # token tasarrufu
        ],
        "verify_raporu": verify_report,
    }


def _parse_debate_json(raw: str) -> dict:
    """Markdown fence'leri kaldırarak JSON parse et."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("debate_json_parse_failed", raw=raw[:200])
        return {"verdict": "retry", "score": 0.5, "issues": ["JSON parse hatası"]}


def _coerce_verdict(value: object) -> DebateVerdict:
    verdict = str(value or "retry").strip().lower()
    if verdict in {"pass", "retry", "reject"}:
        return verdict  # type: ignore[return-value]
    return "retry"


def _coerce_score(value: object) -> float:
    try:
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(score):
        return 0.5
    return min(max(score, 0.0), 1.0)


# --------------------------------------------------------------------------
#  Notes / formatting
# --------------------------------------------------------------------------

def _final(
    state: AgentState,
    verdict: DebateVerdict,
    notes: str,
    *,
    increment_retry: bool = False,
) -> dict:
    """Final state delta — verdict, notes, retry_count."""
    out: dict = {
        "debate_verdict": verdict,
        "debate_notes": notes,
    }
    if increment_retry:
        out["retry_count"] = state.get("retry_count", 0) + 1
    return out


def _build_reject_notes(state: AgentState) -> str:
    """Reject durumunda kullanıcıya gösterilecek not — verify_notes'tan zenginleştir."""
    base = state.get("debate_notes", "")
    contradictions = [
        c for c in state.get("verified_claims", [])
        if "NLI veto" in (c.get("verify_reason", "") or "")
    ]
    if contradictions:
        return f"{base}\nÇelişki tespit edildi: {len(contradictions)} iddia kaynakla uyumsuz."
    return base or "Cevap doğrulanamadı."


def _format_notes(
    verdict: DebateVerdict,
    score: float,
    issues: list,
    rationale: str,
) -> str:
    issues_str = "; ".join(str(i) for i in issues[:5]) if issues else "yok"
    rationale_str = (rationale or "")[:200]
    return (
        f"verdict={verdict} score={score:.2f}\n"
        f"issues: {issues_str}\n"
        f"rationale: {rationale_str}"
    )


__all__ = ("debate_node",)
