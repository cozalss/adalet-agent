"""İçerik-risk veto guard — verify pipeline'ın SIFIR HALÜSİNASYON katmanı.

NLI yalnız doğrudan ÇELİŞKİ yakalar. Bu modül, [src:]-etiketli olduğu için
NLI/fuzzy'den geçen ama TEHLİKELİ olan iki yanlış-çıkarım sınıfını yakalar:

  1. Uydurma kanun adı — "İşçilik Kanunu" (gerçek: İş Kanunu). Kesin hata.
  2. Süre/eşik gerekçeli hak-reddi — "2 yıl kıdem için yetersiz" (md.14 min 1 yıl),
     "5 yıl altında tazminat verilmez" (uydurma eşik). Tehlikeli yanlış-çıkarım.

Gerçek Qwen 14B çıktısında gözlemlendi (2026-05-30). verify_node bu veto'yu
çağırır; bloklayıcı risk varsa fail-closed REJECT (CLAUDE.md §1).

NOT: production guard'ı (eval değil) — eval/answer_risk.py bunları re-export eder.
"""

from __future__ import annotations

import re

# --- Uydurma/yanlış kanun adları (kesin hata) ---
_FABRICATED_LAW_RE = re.compile(
    r"\b(?:"
    r"İşçilik\s+Kanunu|"           # gerçek: İş Kanunu
    r"Kiralama\s+Kanunu|"          # gerçek: TBK kira hükümleri
    r"Tüketicilik\s+Kanunu|"       # gerçek: Tüketicinin Korunması Hk. Kanun
    r"Trafik\s+Yasası|"            # gerçek: Karayolları Trafik Kanunu
    r"Vergi\s+Yasası"              # gerçek: VUK/GVK/KVK
    r")\b",
    re.IGNORECASE,
)

# --- Süre/eşik gerekçeli HAK-REDDİ (sıkı — denial kalıbı) ---
# Yalnız TEHLİKELİ kalıbı yakalar: süre/eşik gerekçe gösterip hak reddeden cümle.
# "1 yıl gerekir" gibi DOĞRU bilgilendirme yakalanmaz (false-positive minimize).
_DENIAL_VERB = (
    r"(?:karşılamı\w*|yetersiz|yeterli\s+değil|hak\s+kazanama\w*|kazanamaz|"
    r"verilmez|verilmeyebilir|alamaz\w*|doğmaz|sağlamı\w*|sağlamaz|"
    r"yeterli\s+olm\w*|geçerli\s+değil|mümkün\s+değil)"
)
_DURATION_OR_THRESHOLD = r"(?:\d+\s*(?:yıl|sene|ay|hafta|gün)|süre\w*|altında|aşağı)"
_NEGATIVE_ELIGIBILITY_RE = re.compile(
    rf"{_DURATION_OR_THRESHOLD}.{{0,80}}?{_DENIAL_VERB}"
    rf"|{_DENIAL_VERB}.{{0,80}}?{_DURATION_OR_THRESHOLD}",
    re.IGNORECASE | re.DOTALL,
)

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def fabricated_law_names(text: str) -> list[str]:
    """Bilinen uydurma/yanlış kanun adlarını döndür (kesin hata)."""
    return [m.group(0) for m in _FABRICATED_LAW_RE.finditer(text)]


def negative_eligibility_claims(text: str) -> list[str]:
    """Süre/eşik gerekçesiyle HAK REDDEDEN cümleler (sıkı, veto için).

    "2 yıl ... karşılamıyor", "5 yıl altında ... verilmeyebilir" gibi TEHLİKELİ
    yanlış-çıkarımları yakalar; "1 yıl gerekir" gibi doğru bilgilendirmeyi
    yakalamaz (false-positive minimize).
    """
    flags = []
    for sent in _SENT_SPLIT_RE.split(text):
        if _NEGATIVE_ELIGIBILITY_RE.search(sent):
            flags.append(sent.strip()[:160])
    return flags


def verify_risk_veto(text: str) -> tuple[bool, list[str]]:
    """Verify pipeline veto kararı: cevapta BLOKLAYICI içerik-riski var mı?

    Bloklayıcı (fail-closed → reject):
      - Uydurma kanun adı (kesin hata)
      - Süre/eşik gerekçeli hak-reddi (tehlikeli yanlış-çıkarım)

    Returns: (bloklanmalı_mı, gerekçe_listesi). CLAUDE.md §1: doğrulanamazsa REDDEDİLİR.
    """
    reasons: list[str] = []
    for law in fabricated_law_names(text):
        reasons.append(f"uydurma kanun adı: {law}")
    for sent in negative_eligibility_claims(text):
        reasons.append(f"süre/eşik gerekçeli hak-reddi: {sent}")
    return (bool(reasons), reasons)
