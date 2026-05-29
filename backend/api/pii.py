"""PII masking — Sprint-4 W6.4.

Türkçe PII pattern'ları:
  - TCKN (11 hane, ilk hane ≠ 0). NOT: checksum doğrulaması KASITLI olarak YOK.
    CLAUDE.md test verisinde geçersiz sahte TCKN (12345678901) kullanıyoruz;
    checksum eklersek bunlar maskelenmez → gizlilik için false-negative. Over-mask
    (her 11 haneyi maskele) fail-safe tercih. — tek modül, eval/edge_cases.py
    ile paylaşılabilir
  - Telefon (TR +90 / 0xxx-xxx-xxxx)
  - Email
  - IBAN (TR + 24 char)
  - Plaka (XX-XXX-XXX veya XX XXX XXX)

Kullanım yeri:
  1. session persist — kullanıcı sorusu loglanırken
  2. structlog processor — log mesajları içinde
  3. audit log — hassas alan olmadan ek olarak hash(question)

Default mask token: "[PII_MASKED]". Geriye dönüşümsüz (de-mask yok).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

import structlog

log = structlog.get_logger()

PII_MASK_TOKEN = os.getenv("PII_MASK_TOKEN", "[PII_MASKED]")
PII_ENABLED = os.getenv("PII_ENABLED", "1").lower() in {"1", "true", "yes"}

# TCKN: 11 hane, ilk ≠ 0. Lookaround ile false-pos azalt.
_TCKN_RE = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")
# Telefon: +90 5xx ... veya 05xx ...
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?90[\s\-]?)?0?5\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)"
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_IBAN_RE = re.compile(r"\bTR\d{2}[\s]?(?:\d{4}[\s]?){5}\d{2}\b")
_PLATE_RE = re.compile(r"\b\d{2}[\s\-]?[A-Z]{1,3}[\s\-]?\d{2,4}\b")


@dataclass(frozen=True)
class MaskResult:
    masked_text: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def has_pii(self) -> bool:
        return self.total > 0


def mask_pii(text: str) -> MaskResult:
    """Tüm PII pattern'larını mask token ile değiştir."""
    if not PII_ENABLED or not text:
        return MaskResult(text, {})

    counts: dict[str, int] = {}
    masked = text

    for name, pat in (
        ("tckn", _TCKN_RE),
        ("phone", _PHONE_RE),
        ("email", _EMAIL_RE),
        ("iban", _IBAN_RE),
        ("plate", _PLATE_RE),
    ):
        matches = pat.findall(masked)
        if matches:
            counts[name] = len(matches)
            masked = pat.sub(PII_MASK_TOKEN, masked)

    if counts:
        log.info("pii_masked", **counts)

    return MaskResult(masked, counts)


def fingerprint(text: str, length: int = 16) -> str:
    """SHA-256 truncated hex — geri-dönüşümsüz kimlik (log-safe).

    email / principal sub gibi PII'yi log / ID / JSONL'e HAM yazmak yerine
    deterministik parmak izi üret: aynı girdi → aynı hash (gruplanabilir) ama
    kimlik açığa çıkmaz. De-mask yok.
    """
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:length]


def hash_question(text: str) -> str:
    """SHA-256 ilk 16 char — audit log için question fingerprint."""
    return fingerprint(text, 16)


__all__ = (
    "PII_ENABLED",
    "PII_MASK_TOKEN",
    "MaskResult",
    "fingerprint",
    "hash_question",
    "mask_pii",
)
