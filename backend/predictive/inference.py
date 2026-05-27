"""Dava sonucu tahmini — heuristic baseline (canlı 8. ajan).

README.md (Sprint-7/8) fine-tuned BERT-TR + 10K etiketli korpus öngörüyor; o
model henüz YOK. Bu modül README'nin **"Aşama-1: Regex + Heuristic (~%70)"**
yaklaşımını canlı bir baseline olarak hayata geçirir: getirilen benzer Yargıtay
kararlarının (emsal) sonuç bölümlerindeki "kabul / ret / kısmen" sinyallerini
oylar, TUTUCU bir tahmin üretir. Yeterli/uyumlu sinyal yoksa dürüstçe "belirsiz".

`predict_outcome()` arayüzü STABİL: Sprint-7/8'de fine-tuned BERT inference
(`to_thread` + model) bu fonksiyonun İÇİNE düşer, çağıranlar (tahmin_node)
değişmez.

KRİTİK (CLAUDE.md §2): Bu bir TAHMİN, mahkeme garantisi DEĞİL. `confidence`
asla `_MAX_CONFIDENCE`'i (0.85) geçmez; verify/debate hard-gate'i bu node'dan
etkilenmez (yalnız display). Belirsizken uydurma kazanma oranı verilmez.
"""

from __future__ import annotations

from collections import Counter

import structlog

from agents.state import Prediction, PredictionClass
from retrieval.turkish_text import tr_lower

log = structlog.get_logger()

# Kesinlik ima etmemek için tavan — heuristic asla "%100 kazanırsın" demez.
_MAX_CONFIDENCE = 0.85
# Anlamlı oylama için gereken minimum sınıflandırılabilir emsal.
_MIN_SIGNAL = 2

# Yargıtay karar sonuç-bölümü kalıpları (tr_lower'lanmış metinde aranır).
# "kısmen ..." önce kontrol edilir: "kısmen kabul" ham "kabul" içerir.
_KISMI_PATTERNS = (
    "kısmen kabul", "kısmen ret", "kısmen reddine", "kısmen kabulüne",
    "kısmen haklı", "kabul ve kısmen",
)
_KAZANDI_PATTERNS = (
    "kabulüne karar", "davanın kabul", "talebin kabul", "talep kabul",
    "kabulüne", "davacı haklı", "lehine karar", "lehine hükm", "haklı bulun",
)
_KAYBETTI_PATTERNS = (
    "reddine karar", "davanın reddi", "talebin reddi", "talep reddedil",
    "reddine", "davacı haksız", "haksız bulun", "aleyhine karar",
)


def _classify_outcome(text_low: str) -> PredictionClass | None:
    """Tek bir emsal kararın sonucunu sinyal-kelimelerinden sınıflandır.

    Döner: "kazandi" | "kaybetti" | "kismi" | None (sinyal yok).
    Karışık (hem kabul hem ret standalone) → "kismi".
    """
    if any(p in text_low for p in _KISMI_PATTERNS):
        return "kismi"
    has_kazandi = any(p in text_low for p in _KAZANDI_PATTERNS)
    has_kaybetti = any(p in text_low for p in _KAYBETTI_PATTERNS)
    if has_kazandi and has_kaybetti:
        return "kismi"  # çelişen sinyal → kısmi
    if has_kazandi:
        return "kazandi"
    if has_kaybetti:
        return "kaybetti"
    return None


_CLASS_TR = {
    "kazandi": "kazanma",
    "kaybetti": "kaybetme",
    "kismi": "kısmen kabul",
    "belirsiz": "belirsiz",
}


def _belirsiz(case_ids: list[str], n_signal: int, n_total: int) -> Prediction:
    # 0 sinyal → 0.0; 1 sinyal → ~0.25 (zayıf işaret ama tek emsal güvenilmez).
    conf = 0.0 if n_signal == 0 else 0.25
    return Prediction(
        verdict_class="belirsiz",
        confidence=conf,
        similar_case_ids=case_ids,
        reasoning=(
            f"{n_total} benzer emsalin yalnız {n_signal} tanesinde net sonuç "
            "sinyali bulundu — güvenilir tahmin için yetersiz. Sonuç davaya özgü "
            "koşullara bağlıdır; bir avukata danışmanızı öneririz."
        ),
    )


def _heuristic_predict(
    similar_case_texts: list[str], similar_case_ids: list[str],
) -> Prediction:
    """Emsal sonuç-oylaması → tutucu tahmin. Saf fonksiyon (test edilebilir)."""
    votes: Counter[PredictionClass] = Counter()
    for text in similar_case_texts:
        outcome = _classify_outcome(tr_lower(text))
        if outcome is not None:
            votes[outcome] += 1

    n_signal = sum(votes.values())
    n_total = len(similar_case_texts)
    if n_signal < _MIN_SIGNAL:
        return _belirsiz(similar_case_ids, n_signal, n_total)

    top_class, top_count = votes.most_common(1)[0]
    agreement = top_count / n_signal
    # Veri yeterliliği faktörü: 2 emsal → 0.7, 5+ emsal → 1.0 ölçek.
    sufficiency = 0.5 + 0.5 * min(n_signal, 5) / 5
    confidence = round(min(agreement * sufficiency, _MAX_CONFIDENCE), 3)

    dist = ", ".join(
        f"{c}={votes[c]}" for c in ("kazandi", "kaybetti", "kismi") if votes[c]
    )
    reasoning = (
        f"{n_total} benzer emsalden {n_signal} tanesinde net sonuç ({dist}). "
        f"Çoğunluk '{_CLASS_TR[top_class]}' yönünde (uyum %{round(agreement * 100)}). "
        "Bu istatistiksel bir tahmindir, mahkeme garantisi değildir."
    )
    return Prediction(
        verdict_class=top_class,
        confidence=confidence,
        similar_case_ids=similar_case_ids,
        reasoning=reasoning,
    )


async def predict_outcome(
    question: str,
    similar_case_texts: list[str],
    similar_case_ids: list[str] | None = None,
) -> Prediction:
    """Soru + benzer emsal metinleri → dava sonucu tahmini.

    Şu an heuristic (emsal oylaması). Sprint-7/8'de fine-tuned BERT-TR inference
    bu fonksiyonun içine girer (arayüz değişmez). `question` heuristic'te şimdilik
    kullanılmıyor ama imza model versiyonu için stabil tutuluyor.
    """
    _ = question  # heuristic'te kullanılmıyor; BERT versiyonunda girdi olacak
    case_ids = list(similar_case_ids or [])
    prediction = _heuristic_predict(similar_case_texts, case_ids)
    log.info(
        "predict_outcome",
        verdict=prediction["verdict_class"],
        confidence=prediction["confidence"],
        n_cases=len(similar_case_texts),
    )
    return prediction


__all__ = ("predict_outcome",)
