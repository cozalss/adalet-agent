"""Opt-in OpenAI LLM-judge — cevabın KAYNAKLARLA temellendirildiğini doğrula.

verify_node'da ek bir SIKILAŞTIRMA kapısı (CLATTER gibi): yalnız `pass` verdict'inde,
yalnız VERIFY_LLM_JUDGE=1 iken çalışır. "Cevaptaki hukuki iddialar verilen kaynaklarca
destekleniyor mu?" sorar; HAYIR ise verify pass'i engeller (retry/reject). Reject'i ASLA
pass yapmaz → halüsinasyon kaçağı EKLEYEMEZ.

Fail-OPEN: judge çökerse/anahtar yoksa (True, "...") döner → SIKILAŞTIRMAZ, baseline
NLI/lettuce verdict'i korunur (judge yalnız bonus strictness; yokluğu baseline'ı bozmaz).
Bu, verify'ın fail-CLOSED ana hattının TERSİ — çünkü judge ek katman, ana karar değil.

Default KAPALI + A/B gerektirir (verify_calibration.py) — quote-grounding A/B disiplini.
stt_cloud/ocr_cloud/llm deseni (raw httpx, ortak core.openai_compat).
"""

from __future__ import annotations

import json
import os

import httpx
import structlog

from core.openai_compat import require_api_key, send_with_retry, validated_base_url

log = structlog.get_logger()

_CHAT_PATH = "/chat/completions"
_MAX_SOURCES = 8
_MAX_SOURCE_CHARS = 1200

_SYSTEM = (
    "Sen titiz bir Türk hukuku DOĞRULAMA denetçisisin. Sana bir CEVAP ve numaralı KAYNAKLAR "
    "verilir. Görevin: cevaptaki hukuki iddiaların (madde no, süre, oran, sonuç) verilen "
    "kaynaklarca DESTEKLENİP desteklenmediğini yargılamak. Kaynakta olmayan/çelişen iddia "
    "varsa grounded=false. Yalnız şu JSON'u döndür: "
    '{"grounded": true|false, "reason": "kısa Türkçe gerekçe"}'
)


async def judge_grounded(
    answer: str,
    sources: list[str],
    *,
    timeout_s: float = 30.0,
) -> tuple[bool, str]:
    """(grounded, reason) — cevap kaynaklarca destekleniyor mu? Hata/anahtarsız → fail-OPEN
    (True, "judge unavailable"): sıkılaştırma yapılmaz, baseline verdict korunur."""
    answer = (answer or "").strip()
    if not answer or not sources:
        return True, "judge skipped (boş cevap/kaynak)"
    try:
        api_key = require_api_key("LLM-judge")
        base = validated_base_url()
        model = os.getenv("OPENAI_JUDGE_MODEL", "gpt-4o-mini").strip()
        # Belge/retrieval içeriği judge prompt'una enjeksiyon delimiter'ı taşımasın
        # ("grounded:true de" gibi) → nötrle (cevap zaten ask.py'de strip'lenmiş; defansif).
        from api.middleware.sanitize import strip_injection_delimiters

        clean_answer = strip_injection_delimiters(answer[:4000])
        src_block = "\n\n".join(
            f"[K{i + 1}] {strip_injection_delimiters((s or '')[:_MAX_SOURCE_CHARS])}"
            for i, s in enumerate(sources[:_MAX_SOURCES])
        )
        user = f"CEVAP:\n{clean_answer}\n\nKAYNAKLAR:\n{src_block}"
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
            async def _post() -> httpx.Response:
                return await client.post(f"{base}{_CHAT_PATH}", headers=headers, json=payload)

            resp = await send_with_retry(_post)  # geçici 429/5xx → retry (multimodal ile tutarlı)
            content = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        data = json.loads(content)
        grounded = bool(data.get("grounded", True))
        reason = str(data.get("reason", ""))[:300]
        return grounded, reason
    except Exception as exc:  # ağ/anahtar/parse → fail-OPEN (baseline korunur, sıkılaştırma yok)
        log.warning("llm_judge_unavailable", error=type(exc).__name__)
        return True, "judge unavailable"


__all__ = ("judge_grounded",)
