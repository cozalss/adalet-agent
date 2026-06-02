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

import asyncio
import json
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog

from agents.state import Prediction, PredictionClass
from retrieval.turkish_text import tr_lower

log = structlog.get_logger()

# Fine-tuned BERT checkpoint (train.py çıktısı). Dizin varsa model kullanılır,
# yoksa heuristic fallback. PREDICTIVE_USE_MODEL=0 ile zorla heuristic.
_MODEL_DIR = os.getenv("PREDICTIVE_MODEL_DIR", "predictive/checkpoints/best")
# BERT inference cihazı — VARSAYILAN CPU: model küçük (110M, p95<200ms CPU),
# production'da GPU llama-server/Qwen'e ayrılır (contention yok). GPU istenirse
# PREDICTIVE_DEVICE=cuda.
_MODEL_DEVICE = os.getenv("PREDICTIVE_DEVICE", "cpu").lower()

# mle-reviewer kritik bulgu: heuristic tüm metni tarayarak gerekçe bölümündeki
# alt-mahkeme atıflarını ("ilk derece reddine") oyluyor → false-label. HÜKÜM
# bölümü genelde "HÜKÜM:" / "SONUÇ:" / "Karar:" başlığıyla başlar. Bu regex
# bölümü izole eder; bulunmazsa son 800 karaktere düşeriz (hüküm tipik olarak
# son paragraflarda).
_HUKUM_HEADER_RE = re.compile(
    r"(?i)\b(h\s*[üu]\s*k\s*[üu]\s*m|sonu[cç])\s*[:\.]\s*",
)
_HUKUM_TAIL_CHARS = 800     # başlık yoksa fallback


def _isolate_hukum(text_low: str) -> str:
    """Karar metninden hüküm bölümünü izole et.

    Strateji: "hüküm:" / "sonuç:" başlığı varsa ondan sonrasını al; yoksa son
    800 karakter (hüküm tipik olarak metnin sonundadır). Bu, gerekçe bölümündeki
    "alt mahkeme reddine" gibi atıfların false-label etmesini önler.
    """
    m = _HUKUM_HEADER_RE.search(text_low)
    if m:
        return text_low[m.end():]
    return text_low[-_HUKUM_TAIL_CHARS:]


def _facts_before_hukum(text: str) -> str:
    """Karar metninin HÜKÜM ÖNCESİ (olay+gerekçe) kısmı — BERT serve girdisi.

    Model eğitim girdisi (input_text) = olay+gerekçe, hüküm HARİÇ (auto_label leak-free).
    Canlıda da BERT'e aynı dağılım verilmeli: emsal kararın hüküm-öncesi metni. Hüküm
    DIŞLANIR → modelin sonucu metinden 'okuyup' kopya çekmesi (sızıntı) önlenir. Başlık
    yoksa tüm metin (kısa snippet'lerde hüküm zaten ayrışmaz). Cased model → orijinal case.
    """
    m = _HUKUM_HEADER_RE.search(text)
    return text[: m.start()] if m else text

# Kesinlik ima etmemek için tavan — heuristic asla "%100 kazanırsın" demez.
_MAX_CONFIDENCE = 0.85
# Anlamlı oylama için gereken minimum sınıflandırılabilir emsal.
_MIN_SIGNAL = 2
# BERT'e girecek emsal-facts'in min uzunluğu (kısa/boş facts kullanılmaz).
_MIN_FACTS_CHARS = 40

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
    """Emsal sonuç-oylaması → tutucu tahmin. Saf fonksiyon (test edilebilir).

    Düzeltme (mle-reviewer bulgusu): metnin tamamını tarama yerine HÜKÜM
    bölümünü izole et. Gerekçe bölümündeki alt-mahkeme atıfları (örn.
    "ilk derece reddine") false-label üretiyordu; hüküm bölümünde ise nihai
    karar (örn. "bozularak kabulüne") yer alır.
    """
    votes: Counter[PredictionClass] = Counter()
    for text in similar_case_texts:
        hukum_low = _isolate_hukum(tr_lower(text))
        outcome = _classify_outcome(hukum_low)
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


def _model_enabled() -> bool:
    """Fine-tuned model kullanılsın mı? (toggle açık VE checkpoint dizini var)."""
    if os.getenv("PREDICTIVE_USE_MODEL", "1").lower() not in {"1", "true", "yes"}:
        return False
    return Path(_MODEL_DIR).is_dir()


@lru_cache(maxsize=1)
def _load_model(model_dir: str) -> tuple[Any, Any, float]:
    """BERT checkpoint + tokenizer + kalibrasyon sıcaklığı yükle (bir kez).

    temperature.json varsa T okunur (calibrate.py çıktısı), yoksa 1.0 (kalibre
    edilmemiş). Heavy import burada (lazy) — modül import'u hafif kalır.
    """
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir).to(_MODEL_DEVICE)
    model.eval()
    temp_path = Path(model_dir) / "temperature.json"
    temperature = 1.0
    if temp_path.exists():
        temperature = float(json.loads(temp_path.read_text(encoding="utf-8"))["temperature"])
    log.info("predict_model_loaded", model_dir=model_dir, temperature=temperature)
    return tok, model, temperature


def _model_predict(
    question: str, similar_case_texts: list[str], case_ids: list[str],
) -> Prediction:
    """Fine-tuned BERT-TR ile kalibre tahmin. Sync (to_thread'den çağrılır).

    KRİTİK (train/serve hizalama): model olay+gerekçe karar metniyle eğitildi → canlıda
    da BERT'e emsal kararların HÜKÜM-ÖNCESİ facts'i verilir (kullanıcının kısa sorusu
    DEĞİL — eski bug). Her emsal için kalibre softmax alınır, emsal üzerinde ORTALAMA
    olasılık → en olası sınıf (heuristic oylamasının yumuşak/BERT karşılığı). Kullanılabilir
    emsal facts yoksa soruya düşülür (degraded; sızıntı yok, hüküm dışlandı).
    """
    import torch

    from predictive.calibrate import softmax
    from predictive.data_loader import ID2LABEL

    tok, model, temperature = _load_model(_MODEL_DIR)
    facts = [f for t in similar_case_texts
             if len((f := _facts_before_hukum(t)).strip()) >= _MIN_FACTS_CHARS]
    if len(facts) < _MIN_SIGNAL:
        # Yeterli emsal-facts yok (≥_MIN_FACTS_CHARS, ≥_MIN_SIGNAL karar) → tek/zayıf
        # emsalden kendinden emin BERT tahmini YANILTICI olur (vatandaşı haklı davadan
        # caydırabilir). Heuristic ile tutarlı: düşük-güven "belirsiz" dön. Eski
        # question-fallback (OOD, çıplak soru) kaldırıldı — sızıntısız + güvenli.
        return _belirsiz(case_ids, len(facts), len(similar_case_texts))
    enc = tok(facts, truncation=True, max_length=512, padding=True,
              return_tensors="pt").to(_MODEL_DEVICE)
    with torch.no_grad():
        logits = model(**enc).logits.cpu().numpy()
    probs = softmax(logits, temperature).mean(axis=0)  # emsal üzerinde ortalama
    top = int(probs.argmax())
    cls: PredictionClass = ID2LABEL[top]  # type: ignore[assignment]
    # Kesinlik ima etmemek için tavan (heuristic ile aynı kural).
    conf = round(min(float(probs[top]), _MAX_CONFIDENCE), 3)
    source = f"{len(facts)} emsal kararın olay+gerekçe metni"
    return Prediction(
        verdict_class=cls,
        confidence=conf,
        similar_case_ids=case_ids,
        reasoning=(
            f"Fine-tuned BERT-TR tahmini ({source}, kalibre T={temperature}). Bu "
            "istatistiksel bir tahmindir, mahkeme garantisi değildir."
        ),
    )


async def predict_outcome(
    question: str,
    similar_case_texts: list[str],
    similar_case_ids: list[str] | None = None,
) -> Prediction:
    """Soru + benzer emsal metinleri → dava sonucu tahmini.

    Checkpoint varsa fine-tuned BERT-TR (kalibre) kullanılır; yoksa heuristic
    (emsal oylaması). Model patlarsa heuristic'e graceful fallback. Arayüz STABİL.
    """
    case_ids = list(similar_case_ids or [])

    if _model_enabled():
        try:
            prediction = await asyncio.to_thread(
                _model_predict, question, similar_case_texts, case_ids,
            )
            log.info(
                "predict_outcome", source="bert",
                verdict=prediction["verdict_class"], confidence=prediction["confidence"],
            )
            return prediction
        except Exception as exc:
            # Model patlarsa cevabı bloke etme — heuristic'e düş (best-effort).
            log.warning("predict_model_failed_fallback", error=str(exc))

    prediction = _heuristic_predict(similar_case_texts, case_ids)
    log.info(
        "predict_outcome", source="heuristic",
        verdict=prediction["verdict_class"], confidence=prediction["confidence"],
        n_cases=len(similar_case_texts),
    )
    return prediction


__all__ = ("predict_outcome",)
