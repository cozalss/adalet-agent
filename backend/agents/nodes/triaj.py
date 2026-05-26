"""Triaj ajanı — soruyu 8 hukuk domain'ine ata.

Strateji:
  1. Hızlı keyword filter (kapsam dışı: ceza/aile) → unknown
  2. Multi-turn: chat_history varsa son turun domain'ini hint olarak ekle
  3. LLM JSON-mode classify (system prompt: triaj.tr.txt)
  4. Düşük güven (< MIN_DOMAIN_CONFIDENCE) → unknown

Sprint-5: chat_history support. Önceki turun domain'i "hint" olarak verilir,
ama LLM yine de yeni soruyu kendi başına değerlendirir. "Devam soruları"
(pronominal referans: "o zaman", "bu durumda") önceki domain'i korur.

Çıkış: state["domain"], state["domain_confidence"], state["triage_reasoning"]
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from agents.config import MIN_DOMAIN_CONFIDENCE, OUT_OF_SCOPE_KEYWORDS
from agents.llm import ChatMessage, get_llm
from agents.state import AgentState, ConversationTurn, Domain
from core.observability import observe_node

log = structlog.get_logger()

VALID_DOMAINS: set[str] = {
    "tuketici", "isHukuku", "kira", "icra",
    "trafik", "vergi", "tapu", "idari", "unknown",
}

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "triaj.tr.txt"

# Devam-sorusu işaretleri (pronominal / contextual) — önceki domain'i koru
_CONTINUATION_MARKERS = (
    "peki", "o zaman", "bu durumda", "böyle", "şöyle", "öyleyse",
    "ya da", "bunun için", "buna göre", "o halde",
)

MAX_HISTORY_TURNS_IN_PROMPT = 5


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _is_out_of_scope(question: str) -> bool:
    """Kapsam-dışı keyword tespiti — kelime sınırı bilinçli.

    Substring kontrolü "vergi cezası" gibi yasal terimlerde yanlış pozitif
    verir ("ceza" ⊂ "cezası"). Bu yüzden \\b kelime sınırı ile match yapıyoruz.
    Ayrıca "ceza" tek başına değil, "ceza hukuku / ceza davası / ceza yargılaması"
    bağlamında match etmeli — bu yüzden multi-token form'lar tercih edilir.
    """
    import re as _re
    q_low = question.lower()
    for kw in OUT_OF_SCOPE_KEYWORDS:
        # Çok-token ise (örn "ceza hukuku") aynen aranır; tek token ise \b ile
        if " " in kw:
            if kw in q_low:
                return True
        else:
            if _re.search(rf"\b{_re.escape(kw)}\b", q_low):
                return True
    return False


def _is_continuation(question: str) -> bool:
    q_low = question.lower().strip()
    return any(q_low.startswith(m) or f" {m}" in q_low[:30] for m in _CONTINUATION_MARKERS)


def _format_history(history: list[ConversationTurn]) -> str:
    """Son N turu prompt'a uygun string'e dök."""
    if not history:
        return "(geçmiş yok — bu ilk soru)"
    recent = history[-MAX_HISTORY_TURNS_IN_PROMPT:]
    lines = []
    for turn in recent:
        role = "KULLANICI" if turn["role"] == "user" else "ASİSTAN"
        content = turn["content"][:400]  # token tasarrufu
        domain_hint = ""
        if turn.get("domain") and turn["domain"] != "unknown":
            domain_hint = f"  [domain: {turn['domain']}]"
        lines.append(f"{role}{domain_hint}:\n{content}\n")
    return "\n".join(lines)


def _last_user_domain(history: list[ConversationTurn]) -> Domain | None:
    """Son user-turda atanmış domain — devam-sorusu inheritance için."""
    for turn in reversed(history):
        if turn["role"] == "user" and turn.get("domain") and turn["domain"] != "unknown":
            return turn["domain"]  # type: ignore[return-value]
    return None


@observe_node(name="triaj")
async def triaj_node(state: AgentState) -> dict:
    question = state["question"]

    if _is_out_of_scope(question):
        log.info("triaj_out_of_scope", question=question[:60])
        return {
            "domain": "unknown",
            "domain_confidence": 0.0,
            "triage_reasoning": "Kapsam dışı: ceza/aile hukuku desteklenmiyor.",
        }

    history: list[ConversationTurn] = state.get("chat_history", []) or []

    # Devam-sorusu kısa-yolu: önceki turun domain'ini koru, LLM çağrısı atlanmaz
    # ama hint olarak prompt'a girer.
    inherited_domain = _last_user_domain(history) if _is_continuation(question) else None

    llm = get_llm()
    system_prompt = _load_prompt()
    if history:
        # Multi-turn prompt'u eklenti olarak append et (yeni prompt dosyası
        # değil — triaj.tr.txt'ye context bloğu ekliyoruz)
        history_block = _format_history(history)
        hint = f"\n[GEÇMİŞ DOMAIN HINT: {inherited_domain}]" if inherited_domain else ""
        system_prompt = (
            f"{system_prompt}\n\n"
            f"--- KONUŞMA BAĞLAMI ---\n{history_block}{hint}\n"
            f"--- /KONUŞMA BAĞLAMI ---"
        )

    # max_tokens=400: 200 yetersiz oldu (Qwen Türkçe reasoning ortasında kesip
    # JSON kapatmıyordu → parse fail → unknown). 400 ile reasoning rahat sığar.
    response = await llm.chat(
        messages=[
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=question),
        ],
        temperature=0.0,
        max_tokens=400,
        json_mode=True,
    )

    domain, confidence, reasoning = _parse_triage_json(response.content)

    # Devam sorusunda LLM unknown derse, inherited'i fallback olarak kullan
    if domain == "unknown" and inherited_domain:
        log.info("triaj_inherited_from_history", inherited=inherited_domain)
        domain = inherited_domain
        confidence = max(confidence, 0.65)
        reasoning = f"Devam sorusu, önceki domain ({inherited_domain}) korundu."

    # Düşük güven veya geçersiz domain → unknown
    if domain not in VALID_DOMAINS or confidence < MIN_DOMAIN_CONFIDENCE:
        log.warning("triaj_low_confidence", domain=domain, confidence=confidence)
        domain, confidence = "unknown", confidence

    log.info(
        "triaj_done",
        domain=domain, confidence=confidence,
        history_turns=len(history), continuation=inherited_domain is not None,
    )
    return {
        "domain": domain,
        "domain_confidence": confidence,
        "triage_reasoning": reasoning,
    }


def _parse_triage_json(raw: str) -> tuple[Domain, float, str]:
    """Sağlam JSON parser — markdown fence vs. fallback."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```"))

    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        log.warning("triaj_json_parse_failed", raw=raw[:200])
        return "unknown", 0.0, f"JSON parse hatası: {raw[:80]}"

    domain = str(obj.get("domain", "unknown")).strip()
    confidence = float(obj.get("confidence", 0.0))
    reasoning = str(obj.get("reasoning", "")).strip()
    return domain, confidence, reasoning  # type: ignore[return-value]
