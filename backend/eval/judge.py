"""LLM-as-Judge + Ragas Faithfulness — generation kalite ölçümü.

Iki tamamlayıcı yaklaşım:

  1. LLM-as-Judge (lokal Qwen): %20 trace üzerinde rastgele örnekleme,
     kullanıcı sorusu + retrieval + cevap → JSON skor.
     {"faithful": 0..1, "complete": 0..1, "tone": 0..1, "notes": "..."}

  2. Ragas Faithfulness: claims atomized → her atomic claim için entailment
     check. Eğer ragas kurulu değilse ya da OPENAI_API_KEY yoksa, lokal
     LLM-as-Judge ile aynı pipeline (manuel atomization + entailment) çalışır.

NOT: CLAUDE.md §3 — production OpenAI/Anthropic API YASAK. Ragas default
OpenAI'a gider; biz bu yolu KAPATIYORUZ. Eval ortamında bile lokal LLM
(MockLLM / Qwen) kullanılır. Ragas import edilemezse degrade-but-continue.

Kullanım (eval/ablation pipeline):
    judge = LLMJudge()
    score = await judge.evaluate(question, context_snippets, answer)
    # score: {"faithful": 0.92, "complete": 0.78, "tone": 0.85, ...}

Sampling:
    if should_sample(call_id, rate=0.20):
        score = await judge.evaluate(...)
        log.info("judge_sampled", call_id=call_id, **score)
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

import structlog

from agents.llm import ChatMessage, get_llm

log = structlog.get_logger()

# Sprint-4 W2.6: sampling 0.20 → 1.0 default. Eski %20 örnekleme 50 vaka
# benchmark'ta ~10 vaka judge edip yüksek varyans yaratıyordu (per-vaka
# faithful skor stokastik LLM doğasından dolayı bench'ler arası ±0.10 oynuyor).
# Tam örneklem deterministic toplamlar için şart; bütün vakalar judge'lanır,
# bench tekrarları aynı sonucu üretir (`temperature=0.0` + JSON-mode + tam kapsam).
# Hızlı eval için `JUDGE_SAMPLE_RATE=0.20` override edilebilir.
JUDGE_SAMPLE_RATE = float(os.getenv("JUDGE_SAMPLE_RATE", "1.0"))
JUDGE_MAX_TOKENS = 512


_JUDGE_SYSTEM = (
    "Sen Türk hukuku için titiz bir CEVAP HAKEMSİN. Verilen (soru, kaynaklar, "
    "cevap) üçlüsünü ŞU üç ölçütle değerlendir:\n"
    "  - faithful: Cevap kaynaklarla TUTARLI mı? (kaynak dışı iddia yok mu?)\n"
    "  - complete: Cevap soruya tam yanıt veriyor mu? (boşluk var mı?)\n"
    "  - tone: Hukuki dil uygun mu? (kesin, profesyonel, açık)\n"
    "Her ölçüt 0.00–1.00 arası float. 1.0 = kusursuz, 0.0 = berbat.\n\n"
    "SADECE şu JSON şemasını döndür (başka metin yazma):\n"
    '{"faithful": 0.0..1.0, "complete": 0.0..1.0, "tone": 0.0..1.0, '
    '"notes": "kısa gerekçe (max 200 char)"}'
)


_JUDGE_USER_TEMPLATE = (
    "SORU:\n{question}\n\n"
    "KAYNAKLAR (max 5):\n{context}\n\n"
    "CEVAP:\n{answer}\n\n"
    "Değerlendir (sadece JSON):"
)


@dataclass(slots=True)
class JudgeScore:
    faithful: float
    complete: float
    tone: float
    notes: str

    def overall(self) -> float:
        """Ağırlıklı ortalama — faithful en önemli."""
        return round(0.5 * self.faithful + 0.3 * self.complete + 0.2 * self.tone, 3)

    def to_dict(self) -> dict:
        return {
            "faithful": self.faithful,
            "complete": self.complete,
            "tone": self.tone,
            "notes": self.notes,
            "overall": self.overall(),
        }


class LLMJudge:
    """Lokal LLM ile cevap kalite değerlendirme. MockLLM uyumlu."""

    async def evaluate(
        self,
        question: str,
        context_snippets: list[str],
        answer: str,
    ) -> JudgeScore:
        if not question or not answer:
            return JudgeScore(0.0, 0.0, 0.0, "boş soru/cevap")

        context_str = "\n\n".join(
            f"[{i+1}] {s[:400]}" for i, s in enumerate(context_snippets[:5])
        ) or "(kaynak yok)"

        user_msg = _JUDGE_USER_TEMPLATE.format(
            question=question, context=context_str, answer=answer[:2000],
        )
        llm = get_llm()
        try:
            resp = await llm.chat(
                messages=[
                    ChatMessage(role="system", content=_JUDGE_SYSTEM),
                    ChatMessage(role="user", content=user_msg),
                ],
                temperature=0.0,
                max_tokens=JUDGE_MAX_TOKENS,
                json_mode=True,
            )
        except Exception as exc:
            log.warning("judge_llm_failed", error=str(exc))
            return JudgeScore(0.0, 0.0, 0.0, f"LLM hata: {exc!s}")

        return _parse_judge_json(resp.content)


def _parse_judge_json(raw: str) -> JudgeScore:
    """Markdown fence-strip + JSON parse + safe defaults."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```"))
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        log.warning("judge_json_parse_failed", raw=raw[:200])
        return JudgeScore(0.0, 0.0, 0.0, "JSON parse hatası")

    return JudgeScore(
        faithful=_clamp01(obj.get("faithful", 0.0)),
        complete=_clamp01(obj.get("complete", 0.0)),
        tone=_clamp01(obj.get("tone", 0.0)),
        notes=str(obj.get("notes", ""))[:200],
    )


def _clamp01(x: object) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


# --------------------------------------------------------------------------
#  Sampling helper — deterministic on call_id
# --------------------------------------------------------------------------

def should_sample(call_id: str, rate: float = JUDGE_SAMPLE_RATE) -> bool:
    """Deterministic sampling — aynı call_id her zaman aynı sonucu verir.

    SHA-256 hash → ilk 8 byte → uint64 / 2^64. Float oran ile karşılaştır.
    Faydası: traceability + ölçüt karşılaştırma; aynı vaka eval'de hep aynı
    şekilde örneklenir.
    """
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    h = hashlib.sha256(call_id.encode("utf-8")).digest()[:8]
    bucket = int.from_bytes(h, "big") / float(1 << 64)
    return bucket < rate


# --------------------------------------------------------------------------
#  Ragas Faithfulness (opsiyonel) — degrade-but-continue
# --------------------------------------------------------------------------

async def ragas_faithfulness(
    question: str,
    context_snippets: list[str],
    answer: str,
) -> float | None:
    """Ragas faithfulness score (atomic claim entailment).

    Yalnız `ragas` kurulu ise ve ragas LLM/Embedding kurumu lokal modellere
    yönlendirilebilirse çalışır. Production'da OpenAI'a yönlendirme YASAK
    (CLAUDE.md §3). Ragas wrapper bunu kurmak karmaşık — bu noktada Sprint-7'de
    `eval/ragas_full.py` ile çözülecek. Şu an basit shim:

      - ragas import → varsa True; manuel sayım yap (LLMJudge.faithful'a düş)
      - ragas yoksa → None döndür (caller LLMJudge'u kullansın)
    """
    try:
        import ragas  # noqa: F401
    except Exception:
        return None
    # Ragas LLM ayarı OpenAI-default; lokal Qwen LangChainLLM wrap'i Sprint-7'de.
    # Şimdilik LLMJudge faithful skorunu döndür ki API'ı tutarlı tutalım.
    judge = LLMJudge()
    score = await judge.evaluate(question, context_snippets, answer)
    return score.faithful


__all__ = (
    "JUDGE_SAMPLE_RATE",
    "JudgeScore",
    "LLMJudge",
    "ragas_faithfulness",
    "should_sample",
)
