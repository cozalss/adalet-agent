"""Response composer — güvenlik kararını metne çeviren doğal dil katmanı.

Bu node karar vermez; karar triaj/verify/debate/finalize hattında verilir.
Görevi yalnızca belirli response_intent'lerde kullanıcıya görünen metni LLM ile
daha doğal yazmaktır. LLM başarısız olursa güvenli fallback metni kullanılır.
"""

from __future__ import annotations

import re

import structlog

from agents.llm import ChatMessage, get_llm
from agents.state import AgentState
from core.observability import observe_node

log = structlog.get_logger()

_REDIRECT_SYSTEM = (
    "Sen ADALET adlı Türkçe hukuk asistanının cevap bestecisisin. "
    "Güvenlik ve kapsam kararları zaten verilmiştir; bu kararı değiştirme. "
    "Kullanıcı hukuk dışı veya kapsam dışı bir soru sorduysa soruyu cevaplama. "
    "Kısa, sıcak, net ve Türkçe yaz."
)

_REDIRECT_USER_TMPL = (
    "Kullanıcının sorusu:\n"
    "<<<SORU\n{question}\nSORU>>>\n\n"
    "Görev:\n"
    "- Bu soruya doğrudan cevap verme.\n"
    "- Bu konuda güvenilir cevap verecek şekilde tasarlanmadığını söyle.\n"
    "- ADALET'in ana amacını belirt: tüketici, iş, kira, icra, trafik, vergi, tapu "
    "ve idari hukuk konularında kaynaklı bilgi vermek.\n"
    "- Kullanıcıyı yaşadığı hukuki durumu birkaç cümleyle anlatmaya yönlendir.\n"
    "- Avukat/disclaimer boilerplate'i ekleme.\n"
    "- 2-4 cümle yaz; madde işareti, kaynak, kanun numarası veya emoji kullanma.\n"
)

_LEGAL_SCOPE_WORDS = (
    "hukuk", "hukuki", "tüketici", "iş", "kira", "icra",
    "trafik", "vergi", "tapu", "idari",
)


@observe_node(name="compose")
async def compose_node(state: AgentState) -> dict[str, object]:
    """response_intent'e göre doğal dil metni üret.

    Şimdilik yalnız `redirect_to_scope` intent'i LLM'e gider. Diğer intent'lerde
    no-op kalır; finalize mevcut hukuki cevap/doğrulama davranışını sürdürür.
    """
    if state.get("response_intent") != "redirect_to_scope":
        return {}

    question = state.get("question", "")
    try:
        llm = get_llm()
        resp = await llm.chat(
            messages=[
                ChatMessage(role="system", content=_REDIRECT_SYSTEM),
                ChatMessage(role="user", content=_REDIRECT_USER_TMPL.format(question=question)),
            ],
            temperature=0.35,
            max_tokens=220,
            json_mode=False,
        )
        composed = _clean_redirect(resp.content)
        if _is_valid_redirect(composed):
            log.info("compose_redirect_done")
            return {"composed_response": composed}
        log.warning("compose_redirect_invalid", sample=composed[:120])
    except Exception as exc:
        log.warning("compose_redirect_failed", error=str(exc) or type(exc).__name__)

    return {"composed_response": redirect_to_scope_fallback()}


def redirect_to_scope_fallback() -> str:
    """LLM composer başarısızsa deterministik güvenli yönlendirme metni."""
    return (
        "Bu konuda güvenilir bir cevap verecek şekilde tasarlanmadım. "
        "Benim ana amacım; tüketici, iş, kira, icra, trafik, vergi, tapu "
        "ve idari hukuk konularında kaynaklı bilgi vermek.\n\n"
        "İstersen yaşadığın hukuki durumu birkaç cümleyle anlat; hangi hakların "
        "ve başvuru yollarının olabileceğine birlikte bakalım."
    )


def _clean_redirect(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines() if not line.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\s+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip().strip('"')


def _is_valid_redirect(text: str) -> bool:
    """LLM çıktısı yönlendirme görevine uyuyor mu, kaba ama güvenli kontrol."""
    if not text or "[MOCK]" in text:
        return False
    if len(text) > 800:
        return False
    low = text.lower()
    if not any(word in low for word in _LEGAL_SCOPE_WORDS):
        return False
    redirect_markers = (
        "tasarlanmad",
        "ana amac",
        "yardımcı olabil",
        "kapsam",
        "görevim dış",
        "görevim değil",
        "görevim yok",
        "uzman değil",
        "yetkin değil",
        "bilgi veremem",
        "danışmanlık",
        "hizmeti sağlıyor",
    )
    if not any(marker in low for marker in redirect_markers):
        return False
    # Kullanıcıya "bugün cuma", "2+2=4" gibi doğrudan cevap vermesini engelleyen
    # hafif bir güvenlik ağı. Asıl sınır prompt'ta; bu sadece bariz kaçakları eler.
    forbidden_patterns = (r"\b2\s*\+\s*2\s*=\s*4\b", r"\bbugün\s+\w+day")
    return not any(re.search(pattern, low) for pattern in forbidden_patterns)


__all__ = ("compose_node", "redirect_to_scope_fallback")
