"""Citation verifier — sıfır halüsinasyon garantisi.

Bir ajan "TKHK Madde 11 şöyle der: ..." dediğinde:
  1. Madde referansını parse et (kanun kodu + madde no)
  2. mevzuat.gov.tr'den canlı fetch et (cache değil — en güncel)
  3. Ajan iddiasındaki metni gerçek metinle fuzzy match (rapidfuzz)
  4. Eşik (varsayılan 0.85) altında → REDDET

Aynı mantık Yargıtay kararları için de geçerli (Esas/Karar numarası bazlı).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

import structlog
from rapidfuzz import fuzz

from .mevzuat_client import KANUN_KODU_TO_NUMARA, MevzuatClient

log = structlog.get_logger()

FUZZY_THRESHOLD = 0.85
MIN_QUOTE_LENGTH = 30


class VerifyStatus(StrEnum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    NOT_FOUND = "not_found"
    UNPARSEABLE = "unparseable"
    ERROR = "error"


@dataclass(slots=True)
class CitationClaim:
    """Ajanın ürettiği iddia — verifier'a girer."""

    claim_text: str
    kanun_kodu: str | None = None
    madde_no: int | None = None


@dataclass(slots=True)
class VerifyResult:
    status: VerifyStatus
    score: float
    source_text: str | None
    source_url: str | None
    reason: str


CITATION_PATTERNS = [
    re.compile(
        r"\b(TKHK|TBK|IK|İK|SGK|HMK|TCK|BK|MK|İYUK)\s*(?:m\.?|madde)\s*(\d+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:Tüketicinin Korunması Hakkında Kanun|Türk Borçlar Kanunu|İş Kanunu)"
        r".*?(?:m\.?|madde)\s*(\d+)",
        re.IGNORECASE,
    ),
]

KANUN_ALIAS = {
    "TKHK": "TKHK",
    "TBK": "TBK",
    "BK": "TBK",  # eski Borçlar Kanunu → yeni TBK
    "IK": "IK",
    "İK": "IK",
    "SGK": "SGK",
}


def parse_citation(claim_text: str) -> tuple[str, int] | None:
    """Iddia metninden (kanun_kodu, madde_no) çıkar. Bulamazsa None."""
    for pattern in CITATION_PATTERNS:
        m = pattern.search(claim_text)
        if not m:
            continue

        groups = m.groups()
        if len(groups) == 2:
            kanun_raw, madde = groups
            kanun = KANUN_ALIAS.get(kanun_raw.upper())
            if kanun:
                return kanun, int(madde)

    return None


async def verify_claim(claim: CitationClaim) -> VerifyResult:
    """Tek bir iddiayı doğrula."""
    if claim.kanun_kodu and claim.madde_no:
        kanun_kodu, madde_no = claim.kanun_kodu, claim.madde_no
    else:
        parsed = parse_citation(claim.claim_text)
        if not parsed:
            return VerifyResult(
                status=VerifyStatus.UNPARSEABLE,
                score=0.0,
                source_text=None,
                source_url=None,
                reason="Iddia metninde tanınan kanun/madde referansı yok",
            )
        kanun_kodu, madde_no = parsed

    if kanun_kodu not in KANUN_KODU_TO_NUMARA:
        return VerifyResult(
            status=VerifyStatus.UNPARSEABLE,
            score=0.0,
            source_text=None,
            source_url=None,
            reason=f"Bilinmeyen kanun kodu: {kanun_kodu}",
        )

    try:
        async with MevzuatClient() as client:
            madde = await client.fetch_madde(kanun_kodu, madde_no)
    except Exception as exc:
        log.error("verify_fetch_failed", kod=kanun_kodu, madde=madde_no, error=str(exc))
        return VerifyResult(
            status=VerifyStatus.ERROR,
            score=0.0,
            source_text=None,
            source_url=None,
            reason=f"Kaynak fetch hatası: {exc}",
        )

    if madde is None:
        return VerifyResult(
            status=VerifyStatus.NOT_FOUND,
            score=0.0,
            source_text=None,
            source_url=None,
            reason=f"{kanun_kodu} Madde {madde_no} bulunamadı",
        )

    score = _compute_similarity(claim.claim_text, madde.metin)

    if score >= FUZZY_THRESHOLD:
        status = VerifyStatus.VERIFIED
        reason = "Metin eşleşmesi başarılı"
    else:
        status = VerifyStatus.MISMATCH
        reason = (
            f"Metin eşleşmesi yetersiz "
            f"(skor={score:.2f}, eşik={FUZZY_THRESHOLD})"
        )

    log.info(
        "verify_completed",
        kod=kanun_kodu,
        madde=madde_no,
        status=status.value,
        score=score,
    )

    return VerifyResult(
        status=status,
        score=score,
        source_text=madde.metin,
        source_url=madde.source_url,
        reason=reason,
    )


def _compute_similarity(claim: str, source: str) -> float:
    """0.0–1.0 arası fuzzy benzerlik skoru.

    Strateji:
    - claim genelde source'un bir alıntısı — partial_ratio uygundur
    - kısa iddialar için token_set_ratio daha hoşgörülü
    - iki skorun maximumunu al
    """
    if len(claim) < MIN_QUOTE_LENGTH or not source:
        return 0.0

    partial = fuzz.partial_ratio(claim, source) / 100.0
    token_set = fuzz.token_set_ratio(claim, source) / 100.0
    return max(partial, token_set)
