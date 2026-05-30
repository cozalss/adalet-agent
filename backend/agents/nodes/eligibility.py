"""Uygunluk ajanı — yapılandırılmış akıl yürütme (Step-3b).

Eşik-uygulama (kıdem 1 yıl, işe iade 6 ay + 30 işçi) tek draft prompt'unda küçük
modelde güvenilir olmuyordu: model hakları eşik kontrolü yapmadan sıralıyordu.
Çözüm — muhakemeyi prose üretiminden AYIR: bu node yalnız bir işe odaklanır →
retrieve edilen her madde için "kaynaktaki eşiği çıkar → kullanıcı olgusuyla
karşılaştır → VAR/YOK/BELİRSİZ" JSON kararı üretir. Draft bu kararları prose'a
çevirir (eşik aritmetiğini artık draft yapmaz).

Eşikler YALNIZCA madde metninden okunur (SIFIR HALÜSİNASYON, CLAUDE.md §1).
Çıkış: state["eligibility"] = [{madde, hak, kosul, saglaniyor, gerekce}, ...]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from agents.config import ELIGIBILITY_ENABLED, ELIGIBILITY_MAX_TOKENS
from agents.llm import ChatMessage, get_llm
from agents.state import AgentState, Citation
from core.observability import observe_node

log = structlog.get_logger()

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "eligibility.tr.txt"
_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")

# Çok madde → tek çağrı; en alakalı ilk N law maddesiyle sınırla (latency + odak).
_MAX_MADDELER = 4
_SNIPPET_CHARS = 450
_VALID_VERDICTS = {"evet", "hayir", "belirsiz"}

_FACT_LABELS = {
    "sure": "Süre", "isci_sayisi": "İşçi sayısı", "tutar": "Tutar",
    "olay": "Olay", "taraf": "Taraf", "tarih": "Tarih",
}

# System mesajı — rol + JSON-only kuralı. MockLLM dispatch bu marker'dan
# ("uygunluk değerlendir") eligibility çağrısını tanır.
_ELIG_SYSTEM = (
    "Sen Türk hukuku için bir uygunluk değerlendiricisisin. Görevin cevap "
    "yazmak değil; her maddenin eşik/şartını kullanıcı olgularıyla karşılaştırıp "
    "VAR/YOK/BELİRSİZ kararı vermek. Eşikleri yalnız madde metninden al, uydurma. "
    "Çıktın yalnızca geçerli JSON olmalı."
)


@observe_node(as_type="generation", name="eligibility")
async def eligibility_node(state: AgentState) -> dict[str, Any]:
    """Retrieve edilen maddeleri kullanıcı olgularıyla eşik-karşılaştır."""
    if not ELIGIBILITY_ENABLED:
        return {}
    domain = state.get("domain", "unknown")
    if domain == "unknown":
        return {}

    facts = state.get("case_facts") or {}
    law_refs = [r for r in state.get("mevzuat_refs", []) if r.get("doc_type") == "law"]
    if not law_refs:
        return {}
    # Olgu yoksa eşik karşılaştırması anlamsız — draft kendi prompt'uyla idare eder.
    if not facts:
        log.info("eligibility_skipped_no_facts", domain=domain)
        return {}

    maddeler = law_refs[:_MAX_MADDELER]
    user_prompt = (
        _TEMPLATE
        .replace("{olgular_blogu}", _format_facts(facts))
        .replace("{maddeler_blogu}", _format_maddeler(maddeler))
    )

    llm = get_llm()
    try:
        resp = await llm.chat(
            messages=[
                ChatMessage(role="system", content=_ELIG_SYSTEM),
                ChatMessage(role="user", content=user_prompt),
            ],
            temperature=0.0,
            max_tokens=ELIGIBILITY_MAX_TOKENS,
            json_mode=True,
        )
        assessments = _parse(resp.content, {r["source_id"] for r in maddeler})
    except Exception as exc:
        # Best-effort: çökerse draft kendi eşik-prompt'uyla devam eder (degrade).
        log.warning("eligibility_failed", error=str(exc) or type(exc).__name__)
        return {}

    n_yes = sum(1 for a in assessments if a.get("saglaniyor") == "evet")
    n_no = sum(1 for a in assessments if a.get("saglaniyor") == "hayir")
    log.info(
        "eligibility_done",
        domain=domain, n=len(assessments), n_yes=n_yes, n_no=n_no,
    )
    return {"eligibility": assessments}


def _format_facts(facts: dict[str, Any]) -> str:
    parts = [
        f"- {_FACT_LABELS.get(k, k)}: {str(v).strip()}"
        for k, v in facts.items() if str(v).strip()
    ]
    return "\n".join(parts) if parts else "(belirgin olgu yok)"


def _format_maddeler(refs: list[Citation]) -> str:
    lines = []
    for r in refs:
        lines.append(
            f"[{r['source_id']}] {r['title']}\n  {(r['snippet'] or '')[:_SNIPPET_CHARS]}"
        )
    return "\n\n".join(lines)


def _parse(raw: str, known_ids: set[str]) -> list[dict[str, Any]]:
    """Eligibility JSON'unu sağlam parse et + alanları doğrula."""
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(
            ln for ln in text.splitlines() if not ln.startswith("```")
        )
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        log.warning("eligibility_json_parse_failed", raw=raw[:200])
        return []

    raw_list = obj.get("degerlendirmeler", []) if isinstance(obj, dict) else []
    out: list[dict[str, Any]] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        verdict = str(item.get("saglaniyor", "")).strip().lower()
        if verdict not in _VALID_VERDICTS:
            continue
        out.append({
            "madde": str(item.get("madde", "")).strip(),
            "hak": str(item.get("hak", "")).strip()[:120],
            "kosul": str(item.get("kosul", "")).strip()[:200],
            "saglaniyor": verdict,
            "gerekce": str(item.get("gerekce", "")).strip()[:200],
        })
    return out
