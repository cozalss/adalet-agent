"""MockLLM + mock JSON dispatch — test/CI deterministik LLM.

Production llm.py'den AYRI (CLAUDE.md <800 satır + kohezyon: test-kodu prod modülünü
şişirmesin). `from agents.llm import MockLLM` geriye-uyumu llm.py sonunda re-export ile korunur.
ChatMessage/LLMResponse llm.py'den import edilir (llm.py bunu DİP'te import eder → circular-safe).
"""

from __future__ import annotations

import json
from typing import Any

from agents.llm import ChatMessage, LLMResponse


class MockLLM:
    """Test/CI client — gerçek model yok, deterministik dummy yanıt.

    JSON mode'da geçerli {"label": "...", "confidence": ...} döner ki
    LangGraph akışı çalıştığı test edilebilsin.
    """

    def __init__(self, fixed_response: str | None = None) -> None:
        self.fixed_response = fixed_response
        self.call_count = 0

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        # MockLLM json_schema'yı yok sayar (gerçek grammar yok); json_mode davranışı korunur.
        self.call_count += 1
        if self.fixed_response is not None:
            content = self.fixed_response
        elif json_mode:
            content = _mock_json_response(messages)
        else:
            content = (
                "[MOCK] Test cevabı — gerçek LLM bağlanmadı. "
                "Bu mock yanıt LangGraph akışını doğrulamak içindir. "
                "Kaynaklara dayalı gerçek hukuki sentez yalnız llamacpp modunda yapılır."
            )
        return LLMResponse(content=content)


# MockLLM için kaba domain keyword routing — sadece smoke test akışı için
_MOCK_DOMAIN_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("isHukuku",   ("kıdem", "ihbar", "işçi", "mobbing", "fazla mesai")),
    ("kira", ("kira", "depozito", "tahliye", "ev sahibi", "kiracı")),
    ("tuketici",   ("tüketici", "ayıplı", "garanti", "iade", "satın al")),
    ("icra",       ("icra", "haciz", "borç", "takip")),
    ("trafik",     ("trafik", "kaza", "sigorta", "ehliyet", "plaka")),
    ("vergi",      ("vergi", "kdv", "ötv")),
    ("tapu",       ("tapu", "mülkiyet", "kat mülkiyeti")),
    ("idari",      ("kamulaştırma", "vatandaşlık", "idari")),
]


def _mock_domain_from_messages(messages: list[ChatMessage]) -> str:
    """Son user mesajından kaba keyword tabanlı domain — sadece MockLLM için."""
    user_text = " ".join(m.content for m in messages if m.role == "user").lower()
    for domain, kws in _MOCK_DOMAIN_KEYWORDS:
        if any(kw in user_text for kw in kws):
            return domain
    return "unknown"


# Mock JSON şablonları — _mock_json_response dispatch table.
_MOCK_PARAPHRASE_BASE = "soru"  # _multi_query_paraphrases içinde override edilir


def _mock_multi_query_paraphrases(messages: list[ChatMessage]) -> str:
    user_text = " ".join(m.content for m in messages if m.role == "user")
    base = user_text.strip()[:120] or _MOCK_PARAPHRASE_BASE
    return json.dumps(
        {"paraphrases": [f"[MOCK paraphrase {i}] {base}" for i in range(1, 5)]},
        ensure_ascii=False,
    )


# (predicate(system_text) -> bool, payload_builder(messages, system_text) -> str)
# Sıra önemli: önce spesifik, sonra genel ("hakem"/"verdict" en sonda kalsın).
_MOCK_DISPATCH: tuple[tuple[Any, Any], ...] = (
    (lambda s: "paraphrases" in s,
     lambda msgs, _s: _mock_multi_query_paraphrases(msgs)),
    (lambda s: "faithful" in s and "complete" in s,
     lambda _m, _s: json.dumps(
         {"faithful": 0.85, "complete": 0.75, "tone": 0.80,
          "notes": "[MOCK] Judge: ölçütler test seviyesinde."},
         ensure_ascii=False)),
    (lambda s: "self-rag" in s or ("retrieve" in s and "supported" in s and "utility" in s),
     lambda _m, _s: json.dumps(
         {"retrieve": "no", "supported": "yes", "utility": 5,
          "notes": "[MOCK] Self-RAG: yansıma testi, tüm reflection tokens pozitif."},
         ensure_ascii=False)),
    (lambda s: "claim" in s and ("çıkart" in s or "atomic" in s),
     lambda _m, _s: json.dumps(
         {"claims": ["[MOCK] Atomic claim 1.", "[MOCK] Atomic claim 2."]},
         ensure_ascii=False)),
    (lambda s: "uygunluk değerlendir" in s,
     lambda _m, _s: json.dumps(
         {"degerlendirmeler": [
             {"madde": "m-MOCK-1", "hak": "[MOCK] hak", "kosul": "-",
              "saglaniyor": "belirsiz", "gerekce": "[MOCK] uygunluk testi."},
         ]},
         ensure_ascii=False)),
    (lambda s: "entailment" in s,
     lambda _m, _s: json.dumps(
         {"verdict": "yes", "reason": "[MOCK] context destekliyor."},
         ensure_ascii=False)),
    (lambda s: "soru üretici" in s or ("questions" in s and "soru" in s),
     lambda _m, _s: json.dumps(
         {"questions": ["[MOCK] Test sorusu 1?", "[MOCK] Test sorusu 2?"]},
         ensure_ascii=False)),
    (lambda s: "kaynak hakem" in s or "useful" in s,
     lambda _m, _s: json.dumps(
         {"useful": "yes", "reason": "[MOCK] kaynak gerekli."},
         ensure_ascii=False)),
    (lambda s: "hakem" in s or "verdict" in s or "constitutional" in s,
     lambda _m, _s: json.dumps(
         {"verdict": "pass", "score": 0.78, "issues": [],
          "revised_answer": None,
          "rationale": "[MOCK] Debate hakem: taslak kaynaklarla tutarlı görünüyor."},
         ensure_ascii=False)),
)


def _mock_json_response(messages: list[ChatMessage]) -> str:
    """MockLLM json_mode router — system prompt'tan hangi node çağırdığını anla.

    Dispatch table: _MOCK_DISPATCH (predicate, builder) sırayla denenir; ilk eşleşme
    döner. Hiçbiri eşleşmezse default triaj cevabı.
    """
    system_text = " ".join(m.content for m in messages if m.role == "system").lower()
    for predicate, builder in _MOCK_DISPATCH:
        if predicate(system_text):
            return str(builder(messages, system_text))
    domain = _mock_domain_from_messages(messages)
    return json.dumps(
        {"domain": domain, "confidence": 0.85, "reasoning": "MockLLM tahmini"},
        ensure_ascii=False,
    )


__all__ = ("MockLLM",)
