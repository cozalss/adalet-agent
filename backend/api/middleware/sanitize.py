"""Prompt-injection runtime filter — Sprint-4 W6.3.

İki seviye:
  - HARD reject: net jailbreak/scope-bypass kalıpları → 400 Bad Request
  - SOFT sanitize: yumuşak müdahaleler (örn. system-role taklit etiketleri)
    → kullanıcının soru metninden çıkarılır, edit edilmiş hali geri döner

Strateji:
- Türkçe + İngilizce yaygın PI kalıpları
- `eval/edge_cases.py:_PI_PATTERNS` ile aynı corpus (single source of truth)
- LLM çağrısı yapmaz (deterministic, ucuz)
- False-positive maliyet: ENV `SANITIZE_HARD_BLOCK=0` ile soft-only moda alınır

NOT: Bu filter retrieval ve agent graph ÖNCESİ çalışır. Layered defense:
verify katmanı + debate katmanı ek koruma sağlar.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import structlog

log = structlog.get_logger()

SANITIZE_ENABLED = os.getenv("SANITIZE_ENABLED", "1").lower() in {"1", "true", "yes"}
SANITIZE_HARD_BLOCK = os.getenv("SANITIZE_HARD_BLOCK", "1").lower() in {"1", "true", "yes"}

# Hard reject: net jailbreak/system-role injection
_HARD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bignore (all |previous |above )?(instructions|prompts|rules)\b"),
    re.compile(r"(?i)önceki (talimatları|kuralları|sistemi|talimatlari) (unut|yok say|hiçe say)"),
    re.compile(r"(?i)\bjailbreak\b"),
    re.compile(r"(?i)\bDAN\s+(mode|moduna)\b"),
    re.compile(r"(?i)\byou are no longer\b.*\b(assistant|claude|gpt)\b"),
    re.compile(r"(?i)artık (sen )?(bir |hiçbir )?(disclaimer|kural|kurali|filter|filtre) (kullanmazsın|kullanmazsin|uygulamazs)"),
    re.compile(r"(?i)sistem (prompt|talimat|talimati|kurali|kuralı)(ı|i|u|si)?(nı|ni)?\s+(göster|gönder|paylaş|yazdır|yazdir|dök)"),
    re.compile(r"(?i)show me (your |the )?(system|hidden) prompt"),
    re.compile(r"(?i)leak (your |the )?(system|hidden) prompt"),
    re.compile(r"(?i)reveal (your |the )?(system|hidden) prompt"),
)

# Soft sanitize: kullanıcı sorusundan çıkar
# NOT: [SYSTEM] etiketi yalnız etiket+kısa açıklama temizler; tüm metni
# yutmasın diye max-100 char veya satır sonu sınırı.
_SOFT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\[SYSTEM\][^\n\[\.]{0,120}"),
    re.compile(r"\[/?INST\]"),
    re.compile(r"<\|im_start\|>system[^<]*<\|im_end\|>"),
    re.compile(r"###\s*SYSTEM[^\n]*\n"),
    re.compile(r"(?i)^assistant:\s*", re.MULTILINE),
)


@dataclass(frozen=True)
class SanitizeResult:
    blocked: bool
    reason: str
    cleaned_text: str
    matched_hard: list[str]
    matched_soft: list[str]


def sanitize_question(text: str) -> SanitizeResult:
    """Sorudaki PI kalıplarını tespit et + sanitize et.

    Returns:
        SanitizeResult — blocked=True ise 400 dön; aksi halde cleaned_text
        kullanılır.
    """
    if not SANITIZE_ENABLED or not text:
        return SanitizeResult(False, "", text, [], [])

    matched_hard: list[str] = []
    for pat in _HARD_PATTERNS:
        m = pat.search(text)
        if m:
            matched_hard.append(m.group(0)[:80])

    matched_soft: list[str] = []
    cleaned = text
    for pat in _SOFT_PATTERNS:
        m = pat.search(cleaned)
        if m:
            matched_soft.append(m.group(0)[:80])
            cleaned = pat.sub(" ", cleaned)

    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if matched_hard and SANITIZE_HARD_BLOCK:
        log.warning(
            "sanitize_hard_block",
            patterns_matched=len(matched_hard),
            sample=matched_hard[0],
        )
        return SanitizeResult(
            True, f"prompt injection tespit edildi ({len(matched_hard)} kalıp)",
            cleaned, matched_hard, matched_soft,
        )

    if matched_soft:
        log.info("sanitize_soft_clean", patterns_matched=len(matched_soft))

    return SanitizeResult(False, "", cleaned, matched_hard, matched_soft)


__all__ = (
    "SANITIZE_ENABLED",
    "SANITIZE_HARD_BLOCK",
    "SanitizeResult",
    "sanitize_question",
)
