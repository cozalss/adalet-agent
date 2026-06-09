"""Hafif metin yardımcıları — AĞIR bağımlılık YOK (torch/qdrant/transformers çekmez).

agents/ (LLM-siz deterministik policy/triaj/smalltalk/finalize) + retrieval/ ortak
kullanır. Tek kanonik (denetim #40): eskiden `_tr_lower` 4 ajan-modülünde + retrieval/
turkish_text'te ayrı ayrı tanımlıydı. core hafif olduğundan policy.py gibi modüllere
torch coupling'i getirmeden paylaşılır.
"""

from __future__ import annotations


def tr_lower(s: str) -> str:
    """Türkçe-doğru küçük harf: İ→i, I→ı.

    Python `str.lower()` "İ"yi combining nokta'lı "i̇" yapar (→ "i"-başlangıçlı anahtar
    eşleşmelerini bozar) ve "I"yı "i" yapar (Türkçe'de "ı" olmalı). Önce İ/I eşlenir,
    sonra standart lower(). İ ve I disjoint karakterlerdir ve birbirini üretmez →
    replace sırası sonucu DEĞİŞTİRMEZ.
    """
    return s.replace("İ", "i").replace("I", "ı").lower()
