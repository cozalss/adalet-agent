"""Public URL helpers for the official Mevzuat Bilgi Sistemi."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

MEVZUAT_PUBLIC_BASE = "https://www.mevzuat.gov.tr/mevzuat"
DEFAULT_MEVZUAT_TUR = "1"
DEFAULT_MEVZUAT_TERTIP = "5"


def build_mevzuat_url(
    mevzuat_no: str | int,
    mevzuat_tur: str | int | None = None,
    mevzuat_tertip: str | int | None = None,
) -> str:
    """Build the currently working public MBS detail URL."""
    params = {
        "MevzuatNo": str(mevzuat_no),
        "MevzuatTur": str(mevzuat_tur or DEFAULT_MEVZUAT_TUR),
        "MevzuatTertip": str(mevzuat_tertip or DEFAULT_MEVZUAT_TERTIP),
    }
    return f"{MEVZUAT_PUBLIC_BASE}?{urlencode(params)}"


def normalize_mevzuat_url(url: str, metadata: Mapping[str, Any] | None = None) -> str:
    """Normalize old mevzuat.gov.tr links that 404 without MevzuatTertip.

    Existing Qdrant payloads contain URLs like
    ``https://mevzuat.gov.tr/mevzuat?MevzuatNo=6098&MevzuatTur=1``. The official
    site now requires ``MevzuatTertip=5`` for these detail pages.
    """
    metadata = metadata or {}
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    if host and "mevzuat.gov.tr" not in host:
        return url

    query = parse_qs(parsed.query)
    mevzuat_no = _first(query, "MevzuatNo") or metadata.get("mevzuat_no") or metadata.get("kanun_numarasi")
    if not mevzuat_no:
        return url

    mevzuat_tur = _first(query, "MevzuatTur") or metadata.get("mevzuat_tur") or DEFAULT_MEVZUAT_TUR
    mevzuat_tertip = (
        _first(query, "MevzuatTertip")
        or metadata.get("mevzuat_tertip")
        or DEFAULT_MEVZUAT_TERTIP
    )
    return build_mevzuat_url(mevzuat_no, mevzuat_tur, mevzuat_tertip)


def _first(query: Mapping[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None
