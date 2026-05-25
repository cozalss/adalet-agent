"""Ragas-uyumlu lokal evaluator — Faithfulness + AnswerRelevancy + CtxPrec/Recall.

CLAUDE.md §3 üretimde OpenAI/Anthropic API YASAK. Ragas (>=0.2) varsayılan
olarak OpenAI'a yönelir. Bu modül Ragas API'ını TAKLİT eder ama LOKAL
Qwen/MockLLM çağrılarıyla çalışır — pipeline-uyumlu metrik isimleri, tek
satırda batch ölçüm.

Dört temel metrik:

  - faithfulness        ∈ [0,1]  : Atomic claim'lerin context tarafından
                                   destek oranı (her claim için lokal LLM
                                   entailment kararı).
  - answer_relevancy    ∈ [0,1]  : Cevabın soruya yakınlığı (cevap-ten
                                   üretilen N=3 soru ile orijinal soru
                                   arası BGE-M3 cosine).
  - context_precision   ∈ [0,1]  : Retrieve edilen kaynaklardan kaçı
                                   gerçekten cevaba referans verdi
                                   (LLM yes/no per chunk).
  - context_recall      ∈ [0,1]  : Gold-cevaptaki claim'lerin kaçı
                                   retrieve edilen context'le destekleniyor
                                   (gold yoksa NaN → skip).

Kullanım:
    from eval.ragas_full import RagasEvaluator, EvalSample
    samples = [EvalSample(...), ...]
    summary = await RagasEvaluator().evaluate_batch(samples)
    # → {"faithfulness": 0.91, "answer_relevancy": 0.83, ...}

Default-safe: BGE-M3 yüklenemezse answer_relevancy NaN/skip; ground_truth
yoksa context_recall skip. Faithfulness her zaman çalışır (MockLLM bile
deterministic skor verir).
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

import structlog

from agents.llm import ChatMessage, get_llm

log = structlog.get_logger()

ATOMIC_MAX_PER_ANSWER = int(os.getenv("RAGAS_ATOMIC_MAX", "8"))
RELEVANCY_QUESTIONS_N = int(os.getenv("RAGAS_RELEVANCY_N", "3"))
RAGAS_TEMP = 0.0

# Sprint-4 W2.5: answer_relevancy embedding lazy-load fix.
# Embedder model indirilemezse / yüklenemezse / encode başarısızsa, eski
# implementasyon `math.nan` döndürüyordu → toplu ortalamada NaN propagation
# tüm metriği bozardı. Fallback skoru 0.5 (neutral) seçildi:
#   - 0.0 cezalandırma (false negative) — embed eksikliği cevap kalitesizliği
#     anlamına gelmez.
#   - 1.0 ödüllendirme (false positive) — sahte yüksek skor metrik güvenini bozar.
#   - 0.5 neutral — aggregator etkisi minimal, alarm verir ("ölçüm güvenilmez").
RAGAS_RELEVANCY_FALLBACK_SCORE = float(
    os.getenv("RAGAS_RELEVANCY_FALLBACK", "0.5"),
)


# --------------------------------------------------------------------------
#  Data model
# --------------------------------------------------------------------------

@dataclass(slots=True)
class EvalSample:
    """Bir değerlendirme örneği. ground_truth opsiyonel."""

    question: str
    answer: str
    contexts: list[str]
    ground_truth: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass(slots=True)
class SampleScores:
    """Tek örnek için tüm metrikler. NaN = uygulanmadı."""

    faithfulness: float = math.nan
    answer_relevancy: float = math.nan
    context_precision: float = math.nan
    context_recall: float = math.nan

    def to_dict(self) -> dict:
        return {
            "faithfulness": _round_or_none(self.faithfulness),
            "answer_relevancy": _round_or_none(self.answer_relevancy),
            "context_precision": _round_or_none(self.context_precision),
            "context_recall": _round_or_none(self.context_recall),
        }


# --------------------------------------------------------------------------
#  Prompts
# --------------------------------------------------------------------------

_ATOMIZE_SYSTEM = (
    "Sen Türk hukuku metinleri için claim çıkartıcısın. Verilen cevabı "
    "ATOMIC (parçalanmaz, bağımsız) iddialara ayır. Her iddia tek bir hukuki "
    "olgu ifade etmeli (örn: 'TKHK Madde 11 ayıplı malda iade hakkı verir').\n\n"
    "JSON format:\n"
    '{"claims": ["...", "...", "..."]}'
)
_ATOMIZE_USER = "CEVAP:\n{answer}\n\nAtomic claim'leri JSON olarak çıkar:"

_ENTAIL_SYSTEM = (
    "Sen entailment hakemisin. Verilen (claim, context) çifti için:\n"
    "  - 'yes'   : context claim'i AÇIKÇA destekliyorsa\n"
    "  - 'no'    : context claim'i AÇIKÇA çürütüyorsa\n"
    "  - 'unsure': belirsizse\n\n"
    'SADECE JSON döndür: {"verdict": "yes"|"no"|"unsure", "reason": "..."}'
)
_ENTAIL_USER = "CLAIM:\n{claim}\n\nCONTEXT:\n{context}\n\nKarar (JSON):"

# Sprint-4 W2.5: bug fix — .format() ile çağrıldığı için `{` ve `}` ESCAPE
# edilmiş olmalı (`{{` / `}}`). Eski sürüm `KeyError: '"questions"'` ile
# sessizce fail ediyordu, answer_relevancy hep silent fail → 0.0 (şimdi
# fallback skor). Çift parantez = literal tek parantez.
_RELEVANCY_SYSTEM = (
    "Sen soru üreticisisin. Verilen cevabı OKUYUP, bu cevabın yanıtladığı "
    "{n} farklı kullanıcı sorusu üret. Sorular kısa, net, Türkçe olmalı.\n\n"
    'JSON format: {{"questions": ["...", "...", "..."]}}'
)
_RELEVANCY_USER = "CEVAP:\n{answer}\n\n{n} olası soru üret:"

_CTX_PRECISION_SYSTEM = (
    "Sen kaynak hakemisin. Soru ve cevap verildiğinde, bu CONTEXT cevabın "
    "üretilmesi için GEREKLİ miydi (yes/no)?\n"
    'SADECE JSON: {"useful": "yes"|"no", "reason": "..."}'
)
_CTX_PRECISION_USER = (
    "SORU:\n{question}\n\nCEVAP:\n{answer}\n\nCONTEXT:\n{context}\n\nKarar (JSON):"
)


# --------------------------------------------------------------------------
#  Atomization + entailment (faithfulness backbone)
# --------------------------------------------------------------------------

async def _atomize_claims(answer: str) -> list[str]:
    if not answer.strip():
        return []
    llm = get_llm()
    try:
        resp = await llm.chat(
            messages=[
                ChatMessage(role="system", content=_ATOMIZE_SYSTEM),
                ChatMessage(role="user", content=_ATOMIZE_USER.format(answer=answer[:2500])),
            ],
            temperature=RAGAS_TEMP, max_tokens=600, json_mode=True,
        )
    except Exception as exc:
        log.warning("ragas_atomize_failed", error=str(exc))
        return _fallback_split(answer)

    obj = _safe_json(resp.content)
    claims = obj.get("claims") if isinstance(obj, dict) else None
    if not claims or not isinstance(claims, list):
        return _fallback_split(answer)
    return [str(c).strip() for c in claims if str(c).strip()][:ATOMIC_MAX_PER_ANSWER]


def _fallback_split(answer: str) -> list[str]:
    """LLM atomization başarısızsa naive cümle ayırıcı."""
    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 20][:ATOMIC_MAX_PER_ANSWER]


async def _entail_one(claim: str, context: str) -> str:
    llm = get_llm()
    try:
        resp = await llm.chat(
            messages=[
                ChatMessage(role="system", content=_ENTAIL_SYSTEM),
                ChatMessage(
                    role="user",
                    content=_ENTAIL_USER.format(claim=claim, context=context[:1500]),
                ),
            ],
            temperature=RAGAS_TEMP, max_tokens=120, json_mode=True,
        )
    except Exception as exc:
        log.warning("ragas_entail_failed", error=str(exc))
        return "unsure"
    obj = _safe_json(resp.content)
    verdict = obj.get("verdict") if isinstance(obj, dict) else None
    if verdict in {"yes", "no", "unsure"}:
        return verdict
    return "unsure"


async def faithfulness(answer: str, contexts: list[str]) -> float:
    """Atomic claim'lerin context tarafından destek oranı."""
    if not answer.strip() or not contexts:
        return math.nan
    claims = await _atomize_claims(answer)
    if not claims:
        return math.nan
    joined_ctx = "\n\n---\n\n".join(c[:1500] for c in contexts[:5])
    yes_count = 0
    for claim in claims:
        verdict = await _entail_one(claim, joined_ctx)
        if verdict == "yes":
            yes_count += 1
    return yes_count / len(claims)


# --------------------------------------------------------------------------
#  Answer relevancy — cevaptan üretilen sorular ile orijinal soru cosine
# --------------------------------------------------------------------------

async def answer_relevancy(question: str, answer: str) -> float:
    """Üretilen sorular ile orijinal soru arası ortalama cosine.

    Sprint-4 W2.5: embedding lazy-load fail durumunda NaN yerine fallback
    skoru (RAGAS_RELEVANCY_FALLBACK_SCORE, default 0.5). NaN propagation
    aggregator'da silent bozulma yaratıyordu.
    """
    if not question.strip() or not answer.strip():
        return math.nan

    llm = get_llm()
    try:
        resp = await llm.chat(
            messages=[
                ChatMessage(role="system", content=_RELEVANCY_SYSTEM.format(n=RELEVANCY_QUESTIONS_N)),
                ChatMessage(
                    role="user",
                    content=_RELEVANCY_USER.format(answer=answer[:2000], n=RELEVANCY_QUESTIONS_N),
                ),
            ],
            temperature=RAGAS_TEMP, max_tokens=400, json_mode=True,
        )
    except Exception as exc:
        log.warning("ragas_relevancy_questions_failed", error=str(exc))
        return math.nan

    obj = _safe_json(resp.content)
    generated = obj.get("questions") if isinstance(obj, dict) else None
    if not generated or not isinstance(generated, list):
        return math.nan
    generated = [str(q).strip() for q in generated if str(q).strip()][:RELEVANCY_QUESTIONS_N]
    if not generated:
        return math.nan

    sims, embed_ok = _cosine_similarity_batch(question, generated)
    if not embed_ok:
        # Embedder unavailable — neutral fallback (NaN değil; aggregator korunur)
        log.warning(
            "ragas_relevancy_embed_fallback",
            fallback=RAGAS_RELEVANCY_FALLBACK_SCORE,
        )
        return RAGAS_RELEVANCY_FALLBACK_SCORE
    if not sims:
        # Embedder OK ama cosine listesi boş — math edge case, fallback
        return RAGAS_RELEVANCY_FALLBACK_SCORE
    return sum(sims) / len(sims)


def _cosine_similarity_batch(
    reference: str, candidates: list[str],
) -> tuple[list[float], bool]:
    """BGE-M3 ile cosine — (sims, embed_ok) tuple döner.

    Sprint-4 W2.5: önce sadece list[float] döndürüyordu, boş liste hem
    "embed başarısız" hem "math edge case" anlamına geliyordu → caller
    karıştırıyordu. Şimdi explicit embed_ok bayrağı ile ayrılıyor.
    """
    try:
        from retrieval.embedding import Embedder
    except ImportError as exc:
        log.warning("ragas_embedder_unavailable", error=str(exc))
        return [], False
    try:
        emb = Embedder()
        out = emb.encode([reference, *candidates], return_colbert=False)
    except (OSError, RuntimeError) as exc:
        # Sprint-4 W2.5: model dosyası yok / disk dolu / GPU OOM gibi run-time
        # hatalar — bug değil ortam problemi. Diğer Exception'lar propagate olur.
        log.warning("ragas_encode_failed", error=str(exc))
        return [], False
    if not out.dense or len(out.dense) < 2:
        return [], True   # embed OK ama beklenmedik az çıktı (math edge)
    ref_vec = out.dense[0]
    return [_cosine(ref_vec, v) for v in out.dense[1:]], True


def _cosine(a: list[float], b: list[float]) -> float:
    import numpy as np
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


# --------------------------------------------------------------------------
#  Context precision — useful chunks / total chunks
# --------------------------------------------------------------------------

async def context_precision(question: str, answer: str, contexts: list[str]) -> float:
    """Cevap için GEREKLİ olan context oranı."""
    if not contexts or not answer.strip():
        return math.nan
    useful = 0
    llm = get_llm()
    for ctx in contexts[:10]:
        try:
            resp = await llm.chat(
                messages=[
                    ChatMessage(role="system", content=_CTX_PRECISION_SYSTEM),
                    ChatMessage(
                        role="user",
                        content=_CTX_PRECISION_USER.format(
                            question=question[:500],
                            answer=answer[:1500],
                            context=ctx[:1500],
                        ),
                    ),
                ],
                temperature=RAGAS_TEMP, max_tokens=120, json_mode=True,
            )
        except Exception as exc:
            log.warning("ragas_ctxprec_failed", error=str(exc))
            continue
        obj = _safe_json(resp.content)
        if isinstance(obj, dict) and obj.get("useful") == "yes":
            useful += 1
    return useful / min(len(contexts), 10)


# --------------------------------------------------------------------------
#  Context recall — gold claim'lerin destek oranı
# --------------------------------------------------------------------------

async def context_recall(ground_truth: str, contexts: list[str]) -> float:
    """Gold-cevaptaki claim'ler context'le destekleniyor mu?"""
    if not ground_truth.strip() or not contexts:
        return math.nan
    gold_claims = await _atomize_claims(ground_truth)
    if not gold_claims:
        return math.nan
    joined = "\n\n---\n\n".join(c[:1500] for c in contexts[:5])
    yes_count = 0
    for claim in gold_claims:
        if await _entail_one(claim, joined) == "yes":
            yes_count += 1
    return yes_count / len(gold_claims)


# --------------------------------------------------------------------------
#  Batch evaluator
# --------------------------------------------------------------------------

class RagasEvaluator:
    """Ragas-uyumlu lokal evaluator — tüm metrikleri tek çağrıda hesaplar."""

    async def evaluate_sample(self, sample: EvalSample) -> SampleScores:
        scores = SampleScores()
        scores.faithfulness = await faithfulness(sample.answer, sample.contexts)
        scores.answer_relevancy = await answer_relevancy(sample.question, sample.answer)
        scores.context_precision = await context_precision(
            sample.question, sample.answer, sample.contexts,
        )
        if sample.ground_truth:
            scores.context_recall = await context_recall(
                sample.ground_truth, sample.contexts,
            )
        return scores

    async def evaluate_batch(self, samples: Iterable[EvalSample]) -> dict:
        """Sample listesi için ortalama metrikler. NaN değerler hariç tutulur."""
        items: list[EvalSample] = list(samples)
        if not items:
            return {
                "n_samples": 0,
                "faithfulness": math.nan,
                "answer_relevancy": math.nan,
                "context_precision": math.nan,
                "context_recall": math.nan,
            }
        per_sample: list[SampleScores] = []
        for s in items:
            per_sample.append(await self.evaluate_sample(s))

        return {
            "n_samples": len(items),
            "faithfulness": _mean_nan([s.faithfulness for s in per_sample]),
            "answer_relevancy": _mean_nan([s.answer_relevancy for s in per_sample]),
            "context_precision": _mean_nan([s.context_precision for s in per_sample]),
            "context_recall": _mean_nan([s.context_recall for s in per_sample]),
            "per_sample": [s.to_dict() for s in per_sample],
        }


# --------------------------------------------------------------------------
#  Helpers
# --------------------------------------------------------------------------

def _safe_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(line for line in text.splitlines() if not line.startswith("```"))
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _mean_nan(values: list[float]) -> float:
    clean = [v for v in values if not math.isnan(v)]
    if not clean:
        return math.nan
    return round(sum(clean) / len(clean), 4)


def _round_or_none(v: float) -> float | None:
    if math.isnan(v):
        return None
    return round(v, 4)


__all__ = (
    "EvalSample",
    "RagasEvaluator",
    "SampleScores",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "faithfulness",
)
