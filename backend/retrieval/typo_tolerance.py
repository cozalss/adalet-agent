"""Typo-tolerant query normalization for Turkish legal retrieval.

The public contract is deliberately conservative:
- never mutate the user-visible question;
- never fuzzy-correct numbers, article references, dates or law codes;
- produce a small number of deterministic internal query variants.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz, process
from rapidfuzz.distance import Levenshtein

from core.text import tr_lower
from retrieval.turkish_text import LEGAL_SYNONYMS

_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü]+", re.UNICODE)

_TR_ASCII = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "i": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "Ç": "c",
        "Ğ": "g",
        "I": "i",
        "İ": "i",
        "Ö": "o",
        "Ş": "s",
        "Ü": "u",
    }
)

_LAW_CODES = frozenset(
    {
        "bk",
        "dmk",
        "eik",
        "gvk",
        "hmk",
        "iik",
        "ik",
        "isy",
        "kdv",
        "kmk",
        "ktk",
        "kvk",
        "kvkk",
        "sgk",
        "tbk",
        "tkhk",
        "tmk",
        "ttk",
        "vuk",
    }
)
_CITATION_MARKERS = frozenset({"e", "esas", "k", "karar", "m", "madde", "no", "s"})
_MORPHOLOGY_FALSE_FRIENDS = frozenset(
    {
        "borcu",
        "çıkarılma",
        "çıkarmak",
        "haklar",
        "sigortası",
        "süreci",
        "yürütmenin",
    }
)

_BASE_TERMS: tuple[str, ...] = (
    "abonelik",
    "alacaklı",
    "artış",
    "araç muayene",
    "arızalı",
    "ayıplı",
    "ayıplı hizmet",
    "ayıplı mal",
    "belediye",
    "bildirim",
    "bozuk",
    "bozuldu",
    "borca itiraz",
    "borçlu",
    "cayma hakkı",
    "ceza puanı",
    "çalışmıyor",
    "değer kaybı",
    "defolu",
    "depozito",
    "disiplin cezası",
    "ehliyet",
    "emlak vergisi",
    "esas",
    "ev sahibi",
    "fazla mesai",
    "garanti",
    "gecikme faizi",
    "haciz",
    "hakem heyeti",
    "haklı fesih",
    "haksız fesih",
    "haksız şart",
    "hız cezası",
    "hız ihlali",
    "ihbar",
    "ihbar tazminatı",
    "ihtar",
    "ihtarname",
    "iş kazası",
    "iş sözleşmesi",
    "işçi",
    "işe iade",
    "işten atılma",
    "işten çıkarma",
    "işveren",
    "itiraz",
    "kamulaştırma",
    "karar",
    "kat mülkiyeti",
    "kıdem",
    "kıdem tazminatı",
    "kırmızı ışık",
    "kira",
    "kira artışı",
    "kira sözleşmesi",
    "kiracı",
    "konut",
    "maaş",
    "madde",
    "mesafeli satış",
    "mobbing",
    "ödeme emri",
    "ödenmeyen ücret",
    "para iadesi",
    "radar",
    "ruhsat",
    "satıcı",
    "sigorta",
    "sınırı",
    "sözleşme",
    "tahliye",
    "taksitli satış",
    "tam yargı",
    "tapu",
    "tarhiyat",
    "tazminat",
    "tescil",
    "trafik",
    "trafik cezası",
    "tüfe",
    "tüketici",
    "tüketici hakem heyeti",
    "usulsüzlük",
    "uzlaşma",
    "ücret",
    "ürün",
    "vergi",
    "vergi cezası",
    "vergi ziyaı",
    "yıllık izin",
    "yürütmeyi durdurma",
    "zamanaşımı",
    "zımni ret",
)


@dataclass(frozen=True, slots=True)
class TypoCorrection:
    original: str
    corrected: str
    distance: int
    score: float


@dataclass(frozen=True, slots=True)
class QueryVariants:
    original: str
    normalized: str
    corrected: str | None
    ascii_folded: str | None
    corrections: tuple[TypoCorrection, ...]
    variants: tuple[str, ...]


def typo_tolerance_enabled() -> bool:
    return os.getenv("TYPO_TOLERANCE_ENABLED", "1").lower() in {"1", "true", "yes", "on"}


def normalize_for_match(text: str) -> str:
    """NFKC + zero-width strip + Turkish lower + whitespace collapse."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    normalized = _ZERO_WIDTH_RE.sub("", normalized)
    normalized = tr_lower(normalized)
    return _SPACE_RE.sub(" ", normalized).strip()


def ascii_fold(text: str) -> str:
    """Turkish-aware ASCII fold for matching channels, not display."""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    folded = normalized.translate(_TR_ASCII)
    folded = unicodedata.normalize("NFKD", folded)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return _SPACE_RE.sub(" ", folded.lower()).strip()


def _is_protected_token(token: str) -> bool:
    folded = ascii_fold(token).strip(".:/-")
    if not folded:
        return True
    if any(ch.isdigit() for ch in folded):
        return True
    return folded in _LAW_CODES or folded in _CITATION_MARKERS


def _iter_terms(extra_vocabulary: Iterable[str] | None = None) -> Iterable[str]:
    yield from _BASE_TERMS
    for group in LEGAL_SYNONYMS:
        yield from group
    if extra_vocabulary:
        yield from extra_vocabulary


@lru_cache(maxsize=64)
def _vocabulary_index(extra_vocabulary: tuple[str, ...] = ()) -> tuple[dict[str, str], tuple[str, ...]]:
    by_folded: dict[str, str] = {}
    for term in _iter_terms(extra_vocabulary):
        normalized = normalize_for_match(term)
        if not normalized:
            continue
        for token in _TOKEN_RE.findall(normalized):
            if _is_protected_token(token):
                continue
            folded = ascii_fold(token)
            if len(folded) < 3:
                continue
            current = by_folded.get(folded)
            # Prefer the canonical form carrying Turkish characters when aliases collide.
            if current is None or (current == folded and token != folded):
                by_folded[folded] = token
    return by_folded, tuple(by_folded.keys())


def _max_distance(token_len: int) -> int:
    if token_len < 5:
        return 0
    if token_len < 9:
        return 1
    return 2


def _candidate_for_folded(
    folded: str,
    vocab: dict[str, str],
    choices: tuple[str, ...],
) -> tuple[str, int, float] | None:
    exact = vocab.get(folded)
    if exact:
        return exact, 0, 100.0

    max_dist = _max_distance(len(folded))
    if max_dist <= 0:
        return None

    match = process.extractOne(folded, choices, scorer=fuzz.ratio, score_cutoff=82.0)
    if match is None:
        return None
    candidate_folded, score, _idx = match
    distance = Levenshtein.distance(folded, candidate_folded)
    if distance > max_dist:
        return None
    if folded[0] != candidate_folded[0] and distance >= max_dist:
        return None
    return vocab[candidate_folded], int(distance), float(score)


def _split_candidate(
    folded: str,
    vocab: dict[str, str],
    choices: tuple[str, ...],
) -> tuple[str, int, float] | None:
    if len(folded) < 7:
        return None
    for split_at in range(3, len(folded) - 2):
        left = _candidate_for_folded(folded[:split_at], vocab, choices)
        right = _candidate_for_folded(folded[split_at:], vocab, choices)
        if left and right:
            corrected = f"{left[0]} {right[0]}"
            distance = left[1] + right[1]
            score = min(left[2], right[2])
            return corrected, distance, score
    return None


def _correct_token(
    token: str,
    vocab: dict[str, str],
    choices: tuple[str, ...],
) -> TypoCorrection | None:
    if _is_protected_token(token):
        return None
    folded = ascii_fold(token)
    if not folded:
        return None

    candidate = _candidate_for_folded(folded, vocab, choices)
    if candidate is None:
        candidate = _split_candidate(folded, vocab, choices)
    if candidate is None:
        return None

    corrected, distance, score = candidate
    normalized = normalize_for_match(token)
    if corrected == normalized:
        return None
    if not _is_safe_typo_correction(normalized, corrected, distance):
        return None
    return TypoCorrection(
        original=normalized,
        corrected=corrected,
        distance=distance,
        score=score,
    )


def _has_turkish_diacritic(text: str) -> bool:
    return any(ch in text for ch in "çğıöşü")


def _is_safe_typo_correction(original: str, corrected: str, distance: int) -> bool:
    """Reject morphology-like rewrites that are not spelling mistakes."""
    if original in _MORPHOLOGY_FALSE_FRIENDS:
        return False
    original_folded = ascii_fold(original)
    corrected_folded = ascii_fold(corrected)
    if original_folded == corrected_folded:
        return True
    if original_folded.startswith(corrected_folded) or corrected_folded.startswith(original_folded):
        return False
    return not (
        distance == 1
        and len(original_folded) == len(corrected_folded)
        and _has_turkish_diacritic(original)
    )


def build_query_variants(
    question: str,
    *,
    vocabulary: Iterable[str] | None = None,
    include_ascii: bool = False,
    max_variants: int = 2,
    max_corrections: int = 5,
) -> QueryVariants:
    """Build conservative internal query variants for typo-tolerant search."""
    original = str(question or "")
    normalized = normalize_for_match(original)
    if not normalized:
        return QueryVariants(original, "", None, None, (), ())

    extra = tuple(vocabulary or ())
    vocab, choices = _vocabulary_index(extra)
    corrections: list[TypoCorrection] = []

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if len(corrections) >= max_corrections:
            return token
        correction = _correct_token(token, vocab, choices)
        if correction is None:
            return token
        corrections.append(correction)
        return correction.corrected

    corrected = _TOKEN_RE.sub(repl, normalized)
    corrected = _SPACE_RE.sub(" ", corrected).strip()
    corrected_variant = corrected if corrected and corrected != normalized else None

    folded = ascii_fold(normalized)
    ascii_variant = folded if include_ascii and folded and folded != normalized else None

    variants: list[str] = []
    for variant in (corrected_variant, ascii_variant):
        if variant and variant not in {normalized, original} and variant not in variants:
            variants.append(variant)
        if len(variants) >= max_variants:
            break

    return QueryVariants(
        original=original,
        normalized=normalized,
        corrected=corrected_variant,
        ascii_folded=ascii_variant,
        corrections=tuple(corrections),
        variants=tuple(variants),
    )


def typo_retrieval_variants(
    question: str,
    *,
    vocabulary: Iterable[str] | None = None,
    max_variants: int = 2,
) -> list[str]:
    """Return non-original typo-corrected query variants for retrieval fan-out."""
    if not typo_tolerance_enabled():
        return []
    return list(
        build_query_variants(
            question,
            vocabulary=vocabulary,
            include_ascii=False,
            max_variants=max_variants,
        ).variants
    )


def match_variants(
    text: str,
    *,
    vocabulary: Iterable[str] | None = None,
    include_ascii: bool = True,
    max_variants: int = 3,
) -> list[str]:
    """Return normalized forms useful for keyword matching."""
    built = build_query_variants(
        text,
        vocabulary=vocabulary,
        include_ascii=include_ascii,
        max_variants=max_variants,
    )
    out: list[str] = []
    for item in (built.normalized, *built.variants):
        if item and item not in out:
            out.append(item)
    return out


__all__ = (
    "QueryVariants",
    "TypoCorrection",
    "ascii_fold",
    "build_query_variants",
    "match_variants",
    "normalize_for_match",
    "typo_retrieval_variants",
    "typo_tolerance_enabled",
)
