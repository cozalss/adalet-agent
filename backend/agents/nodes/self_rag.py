"""Self-RAG — reflection-guided retrieval karar verici.

Referans: Asai et al. ICLR 2024 — "Self-RAG: Learning to Retrieve, Generate,
and Critique through Self-Reflection" (arxiv:2310.11511).

Klasik RAG her zaman retrieve eder. Self-RAG soruyu önce **reflection
token'larıyla** değerlendirir:

  [RETRIEVE]   = Yes | No        — Bu soru kaynağa ihtiyaç duyar mı?
  [SUPPORTED]  = Yes | Partial | No — Mevcut cevap kaynağa dayanıyor mu?
  [UTILITY]    = 1..5            — Cevap soruyu ne kadar karşılıyor?

Akış ADALET-AGENT içinde:
  1. Self-RAG node draft sonrası gelir
  2. LLM'den reflection tokens iste (JSON)
  3. [RETRIEVE]=Yes ve mevcut retrieval YETERSİZ ise → re-retrieve sinyali
     (verify/debate retry mekanizmasını trigger eder)
  4. [SUPPORTED]=No → reject (verify zaten yapıyor, burası ek katman)
  5. [UTILITY]<3 → retry

Self-RAG verify+debate'in TAMAMLAYICISIDIR — onlarla çakışmaz, sadece "Bu
soru için bu retrieval YETERLI mi?" sorusunu sorar.

Default-safe: ENV `SELF_RAG_ENABLED=0` → node no-op, sadece state'e pas
geçer. Graph akışı değişmez.
"""

from __future__ import annotations

import json
import os

import structlog

from agents.config import LLM_TEMPERATURE, MAX_RETRY
from agents.llm import ChatMessage, get_llm
from agents.state import AgentState

log = structlog.get_logger()

SELF_RAG_ENABLED = os.getenv("SELF_RAG_ENABLED", "0").lower() in {"1", "true", "yes"}
MAX_REFLECT = int(os.getenv("MAX_REFLECT", "2"))
UTILITY_MIN = int(os.getenv("SELF_RAG_UTILITY_MIN", "3"))

_REFLECT_SYSTEM = (
    "Sen Self-RAG hakem ajansın. Verilen (soru, kaynaklar, taslak_cevap) "
    "üçlüsü için ÜÇ reflection token'ı üret:\n\n"
    "  retrieve   = 'yes' | 'no'                — Bu soru kaynak gerektiriyor mu?\n"
    "  supported  = 'yes' | 'partial' | 'no'    — Taslak kaynaklarla destekleniyor mu?\n"
    "  utility    = 1-5 arası tamsayı           — Cevap soruyu ne kadar karşılıyor? (5=tam)\n\n"
    "SADECE şu JSON şemasını döndür (başka metin yazma):\n"
    '{"retrieve": "yes", "supported": "yes", "utility": 5, "notes": "kısa gerekçe"}'
)

_REFLECT_USER_TEMPLATE = (
    "SORU:\n{question}\n\n"
    "KAYNAKLAR ({n_refs} adet, ilk birkaçı):\n{refs}\n\n"
    "TASLAK CEVAP:\n{draft}\n\n"
    "Reflection (sadece JSON):"
)


def _merge_notes(state: AgentState, new: str) -> str:
    """debate_notes'u EZME — debate'in notuna ekle.

    self_rag debate'ten SONRA çalışır; debate'in yazdığı notu (finalize bunu
    kullanır) korumak için üzerine yazmak yerine birleştir.
    """
    existing = (state.get("debate_notes") or "").strip()
    return f"{existing}\n[self_rag] {new}".strip() if existing else new


async def self_rag_node(state: AgentState) -> dict:
    """Reflection-guided değerlendirme. State'e self_rag_signal yazar."""
    if not SELF_RAG_ENABLED:
        return {}  # no-op, state değişmez

    question = state.get("question", "")
    draft = state.get("draft_response", "")
    refs = list(state.get("mevzuat_refs", [])) + list(state.get("emsal_refs", []))

    if not draft:
        return {"debate_notes": _merge_notes(state, "Self-RAG: taslak yok")}

    refs_block = "\n".join(
        f"- {r['title']}: {r['snippet'][:200]}" for r in refs[:5]
    ) or "(kaynak yok)"

    user_msg = _REFLECT_USER_TEMPLATE.format(
        question=question, n_refs=len(refs), refs=refs_block, draft=draft[:1200],
    )

    llm = get_llm()
    try:
        resp = await llm.chat(
            messages=[
                ChatMessage(role="system", content=_REFLECT_SYSTEM),
                ChatMessage(role="user", content=user_msg),
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=300,
            json_mode=True,
        )
    except Exception as exc:
        log.warning("self_rag_llm_failed", error=str(exc))
        return {"debate_notes": _merge_notes(state, "Self-RAG hata: değerlendirme atlandı")}

    reflect = _parse_reflection_json(resp.content)

    retrieve_needed = str(reflect.get("retrieve", "no")).lower() == "yes"
    supported = str(reflect.get("supported", "yes")).lower()
    utility = _coerce_utility(reflect.get("utility", 5))
    notes = str(reflect.get("notes", ""))

    log.info(
        "self_rag_done",
        retrieve=retrieve_needed, supported=supported, utility=utility,
    )

    # Karar:
    # - supported == "no" → reject (verify daha sıkı; burada sinyal)
    # - utility < UTILITY_MIN AND retry hakkı var → retry
    # - retrieve == "yes" AND refs zayıf → retry (re-retrieve trigger)
    # - aksi → pas (current verdict korunur)
    current_verdict = state.get("debate_verdict", "pass")
    new_verdict = current_verdict
    retry_count = int(state.get("retry_count", 0))
    rationale = (
        f"Self-RAG: retrieve={retrieve_needed} "
        f"supported={supported} utility={utility} | {notes[:120]}"
    )

    if supported == "no":
        new_verdict = "reject"
    elif current_verdict != "reject" and (
        utility < UTILITY_MIN or (retrieve_needed and len(refs) < 2)
    ):
        # Self-RAG debate'ten sonra çalıştığı için retry sayacını burada yönetir.
        new_verdict = "reject" if retry_count >= MAX_RETRY else "retry"

    out: dict = {"debate_notes": _merge_notes(state, rationale)}
    if new_verdict != current_verdict:
        out["debate_verdict"] = new_verdict
    if new_verdict == "retry":
        out["retry_count"] = retry_count + 1
    return out


def _parse_reflection_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fail-closed: reflection okunamadı → "destekleniyor" varsayma.
        # supported="no" + utility=0 + retrieve="yes" → retry/yeniden-getir sinyali
        # (sessizce pas geçmek halüsinasyon riskini gizler).
        log.warning("self_rag_json_parse_failed", raw=raw[:200])
        return {
            "retrieve": "yes",
            "supported": "no",
            "utility": 0,
            "notes": "parse hatası — fail-closed",
        }


def _coerce_utility(value: object) -> int:
    try:
        utility = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(5, utility))


__all__ = ("SELF_RAG_ENABLED", "self_rag_node")
