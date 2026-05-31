"""Cevap içerik-risk bayrakları — halüsinasyon-eğilimli cümleleri yüzeye çıkarır.

draft_quality.py FORMAT ölçer (uzunluk, Türkçe-saflık, kaynak-etiketi varlığı).
Bu modül İÇERİK riskini ölçer: cümlenin DOĞRU olup olmadığını otomatik
doğrulayamayız (ground-truth hukuk bilgi tabanı gerekir) ama YÜKSEK RİSKLİ
cümle türlerini tespit edip insan-incelemesi için işaretleriz.

Gerçek çıktıda gözlemlenen sorunlar (2026-05-30, gerçek Qwen 14B):
  - "2 yıllık süre kıdem tazminatı için yeterli değildir" → YANLIŞ (md.14: min 1 yıl)
  - "İşçilik Kanunu" → UYDURMA kanun adı (gerçek: İş Kanunu)
  - Kaynak etiketi olmayan kesin hukuki iddialar

Bayraklar (rate = bayraklı cevap / toplam):
  1. duration_eligibility — sayı+süre-birimi+uygunluk-yargısı (en riskli, manuel doğrula)
  2. fabricated_law — bilinen uydurma/yanlış kanun adları
  3. unsourced_claim — [src:] etiketi olmayan kesin hukuki iddia cümlesi
"""

from __future__ import annotations

import re

# --- 1. Süre-uygunluk iddiaları (en yüksek halüsinasyon riski) ---
# "2 yıl ... yeterli/yetersiz", "1 aydan az ... hak kazanmaz" gibi cümleler.
# Sayı + süre-birimi + uygunluk-yargısı birlikteyse → manuel doğrulama gerekir.
_DURATION_UNIT = r"(?:yıl|sene|ay|hafta|gün)"
_ELIGIBILITY_VERB = (
    r"(?:yeterli|yetersiz|yeter|hak\s+kazan|kazanamaz|kazanır|"
    r"gerekli|gerekir|şart|asgari|minimum|en\s+az|dolma)"
)
_DURATION_CLAIM_RE = re.compile(
    rf"\b\d+\s*{_DURATION_UNIT}\w*\b.{{0,60}}?{_ELIGIBILITY_VERB}",
    re.IGNORECASE | re.DOTALL,
)

# --- 2. Uydurma kanun adları + denial veto: production guard'dan re-export ---
# Bu detektörler artık production verify pipeline'ında da kullanılıyor →
# tek kaynak agents/risk_guard.py. Eval geriye-uyumluluk için re-export eder.
from agents.risk_guard import (
    fabricated_law_names,
)

# --- 3. Kaynaksız hukuki iddia ---
# Kesin hukuki iddia içeren ama [src:] etiketi taşımayan cümle.
_SRC_TAG_RE = re.compile(r"\[src:\s*[^\]]+\]")
_LEGAL_CLAIM_MARKERS = (
    "hak kazan", "zorunlu", "yükümlü", "hakkınız var", "talep edebilir",
    "dava açabilir", "tazminat", "madde", "kanun", "hükmü", "yasal",
)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_BOILERPLATE = ("avukata danış", "bilgilendirme amaç", "hukuki tavsiye değil",
                "kısa cevap:", "ne yapmalı", "durumuna uygulama", "dayanak:")


def duration_eligibility_claims(text: str) -> list[str]:
    """Süre + uygunluk yargısı içeren cümleleri döndür (manuel doğrulama gerekir)."""
    flags = []
    for sent in _SENT_SPLIT_RE.split(text):
        if _DURATION_CLAIM_RE.search(sent):
            flags.append(sent.strip()[:160])
    return flags


def unsourced_legal_claims(text: str) -> list[str]:
    """[src:] etiketi olmayan kesin hukuki iddia cümlelerini döndür."""
    flags = []
    for sent in _SENT_SPLIT_RE.split(text):
        low = sent.casefold()
        if any(b in low for b in _BOILERPLATE):
            continue
        if len(sent.strip()) < 30:
            continue
        has_claim = any(m in low for m in _LEGAL_CLAIM_MARKERS)
        has_src = bool(_SRC_TAG_RE.search(sent))
        if has_claim and not has_src:
            flags.append(sent.strip()[:160])
    return flags


def measure_risk(text: str) -> dict:
    """Tek cevap için içerik-risk bayrakları (sayılar + örnek cümleler)."""
    dur = duration_eligibility_claims(text)
    fab = fabricated_law_names(text)
    uns = unsourced_legal_claims(text)
    return {
        "duration_claims": len(dur),
        "fabricated_laws": len(fab),
        "unsourced_claims": len(uns),
        "has_risk": bool(dur or fab or uns),
        # örnekler (rapor/inceleme için)
        "duration_examples": dur[:3],
        "fabricated_examples": fab[:3],
        "unsourced_examples": uns[:2],
    }
