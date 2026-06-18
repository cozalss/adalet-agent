from __future__ import annotations

from retrieval import hybrid_search as hs
from retrieval.mevzuat_urls import build_mevzuat_url, normalize_mevzuat_url


def test_build_mevzuat_url_includes_tertip():
    assert build_mevzuat_url("6098") == (
        "https://www.mevzuat.gov.tr/mevzuat?"
        "MevzuatNo=6098&MevzuatTur=1&MevzuatTertip=5"
    )


def test_normalize_old_public_url_adds_tertip_and_www():
    old = "https://mevzuat.gov.tr/mevzuat?MevzuatNo=6098&MevzuatTur=1"

    assert normalize_mevzuat_url(old) == (
        "https://www.mevzuat.gov.tr/mevzuat?"
        "MevzuatNo=6098&MevzuatTur=1&MevzuatTertip=5"
    )


def test_normalize_uses_payload_when_url_is_missing_query():
    assert normalize_mevzuat_url(
        "https://mevzuat.gov.tr/madde/TBK/344",
        {"kanun_numarasi": "6098"},
    ) == (
        "https://www.mevzuat.gov.tr/mevzuat?"
        "MevzuatNo=6098&MevzuatTur=1&MevzuatTertip=5"
    )


def test_normalize_keeps_non_mevzuat_urls():
    url = "https://karararama.yargitay.gov.tr/?aranan=123"

    assert normalize_mevzuat_url(url, {"kanun_numarasi": "6098"}) == url


def test_hybrid_result_normalizes_mevzuat_payload_url():
    class Point:
        id = "m-TBK-344"
        score = 0.9
        payload = {
            "chunk_id": "m-TBK-344",
            "text": "madde metni",
            "source": "mevzuat",
            "source_url": "https://mevzuat.gov.tr/mevzuat?MevzuatNo=6098&MevzuatTur=1",
            "domain": "kira",
            "doc_type": "law",
            "kanun_numarasi": "6098",
        }

    result = hs._to_result(Point())

    assert result.source_url == (
        "https://www.mevzuat.gov.tr/mevzuat?"
        "MevzuatNo=6098&MevzuatTur=1&MevzuatTertip=5"
    )
