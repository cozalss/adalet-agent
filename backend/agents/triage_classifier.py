"""DistilBERT-TR domain triaj sınıflandırıcısı — keyword ile LLM arası hızlı kademe.

Fine-tuned model VARSA (TRIAGE_MODEL_DIR) yükler → 8 sivil domain'den birini ~50ms'de
tahmin eder; YOKSA None döner → mevcut LLM triaj yolu KORUNUR (graceful, opt-in).
Böylece model eğitilmeden de sistem aynen çalışır; model gelince LLM yükü düşer (P95 ↓).

`predictive/inference.py` deseninin triaj-domain karşılığı: env toggle + checkpoint
kontrolü, lazy torch/transformers import (modül import'u hafif), hatada fallback.

KRİTİK: Model EMİN DEĞİLSE (confidence < eşik) None döner → LLM kademesi devreye girer.
Bu, yanlış domain'e hızlı-yanlış atamayı önler (kademeli kesinlik: keyword → model → LLM).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog

from agents.state import Domain

log = structlog.get_logger()

# Fine-tuned checkpoint (scripts/triage/train.py çıktısı). Dizin varsa model, yoksa None.
_MODEL_DIR = os.getenv("TRIAGE_MODEL_DIR", "models/triage-distilbert")
# Inference cihazı — VARSAYILAN CPU (model küçük, ~50ms; GPU Qwen'e ayrılır).
_MODEL_DEVICE = os.getenv("TRIAGE_DEVICE", "cpu").lower()
# Model bu güvenin ALTINDAYSA "emin değil" → None (LLM'e düş). Yanlış-hızlı atama önler.
# 0.65: 10-soruluk gerçek-ifade kalibrasyon setinde tüm doğru tahminler ≥0.68 güven
# aldı (val %100); 0.65 eşiği bunları geçirir, gerçek belirsizliği LLM'e bırakır.
_MIN_MODEL_CONFIDENCE = float(os.getenv("TRIAGE_MODEL_MIN_CONF", "0.65"))

# 8 sivil domain — eğitim (gen_data/train) ile inference ORTAK sırası (id ↔ label).
# Bu sıra DEĞİŞTİRİLEMEZ (model checkpoint'i bu indekslemeye göre eğitilir).
TRIAGE_LABELS: tuple[Domain, ...] = (
    "tuketici", "isHukuku", "kira", "icra", "trafik", "vergi", "tapu", "idari",
)


def _model_enabled() -> bool:
    """Fine-tuned model kullanılsın mı? (toggle açık VE checkpoint dizini var)."""
    if os.getenv("TRIAGE_USE_MODEL", "1").lower() not in {"1", "true", "yes"}:
        return False
    return Path(_MODEL_DIR).is_dir()


@lru_cache(maxsize=1)
def _load_model(model_dir: str) -> tuple[Any, Any]:
    """DistilBERT checkpoint + tokenizer yükle (bir kez). Heavy import burada (lazy)."""
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir).to(_MODEL_DEVICE)
    model.eval()
    log.info("triage_model_loaded", model_dir=model_dir)
    return tok, model


def _model_classify(question: str) -> tuple[Domain, float]:
    """DistilBERT-TR ile (domain, confidence). Sync (asyncio.to_thread'den çağrılır)."""
    import torch

    tok, model = _load_model(_MODEL_DIR)
    enc = tok(question, truncation=True, max_length=128, return_tensors="pt").to(_MODEL_DEVICE)
    with torch.no_grad():
        probs = torch.softmax(model(**enc).logits[0], dim=-1)
    top = int(probs.argmax())
    return TRIAGE_LABELS[top], float(probs[top])


def classify_domain(question: str) -> tuple[Domain, float] | None:
    """Soruyu 8 domain'den birine ata (fine-tuned model varsa).

    Döner: (domain, confidence) — model var VE güven ≥ eşik;
           None — model yok / güven düşük / hata → çağıran LLM triaja düşer.

    Sync + graceful: model yoksa torch import edilmeden hemen None döner (CI/test
    bağımlılıksız çalışır). Hata olursa loglanıp None (akış bozulmaz).
    """
    if not _model_enabled():
        return None
    try:
        domain, conf = _model_classify(question)
    except Exception as exc:  # model bozuk/eksik → LLM'e düş (best-effort)
        log.warning("triage_model_failed", error=str(exc) or type(exc).__name__)
        return None
    if conf < _MIN_MODEL_CONFIDENCE:
        log.info("triage_model_low_conf", domain=domain, confidence=round(conf, 3))
        return None
    log.info("triage_model_path", domain=domain, confidence=round(conf, 3))
    return domain, conf


__all__ = ("TRIAGE_LABELS", "classify_domain")
