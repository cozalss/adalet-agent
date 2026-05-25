"""Yargıtay regression test — Sprint-4 W5.5.

8 landmark Yargıtay/Danıştay kararı fixture'ları. Bu test'in amacı: bir önceki
sprint'te düzelttiğimiz spesifik hatanın geri gelmemesi (regression guard).

Fixture'lar gerçek karar metni değil; karar üzerine yapılan sentetik
soru-cevap çıkarımları (CLAUDE.md: KVKK/lisans uyumlu sentetik).

Test koşturma:
    uv run pytest tests/eval/test_yargitay_regression.py -v
"""

from __future__ import annotations

import pytest

from agents.config import (
    FUZZY_SUPPORT_THRESHOLD,
    NLI_CONTRADICTION_THRESHOLD,
)
from agents.state import Citation, Claim
from agents.verifier_layers import layer1_rules, layer2_fuzzy

# 8 landmark karar — alan dağılımı:
# 2 İK, 2 Tüketici, 2 Kira, 2 İcra/Vergi
YARGITAY_LANDMARK_CASES = [
    {
        "id": "Y-9HD-2019-1234",
        "domain": "isHukuku",
        "question": "Kıdem tazminatı için ne kadar süre çalışmış olmalı?",
        "expected_madde": "İK m.14",
        "expected_kanun": "1475",
        "verified_claim": (
            "İşçinin kıdem tazminatına hak kazanması için "
            "en az 1 yıl çalışmış olması gerekir (İK m.14)."
        ),
        "fabricated_claim_no": "9999",  # Hallucination guard
    },
    {
        "id": "Y-22HD-2020-456",
        "domain": "isHukuku",
        "question": "Fazla mesai ücreti nasıl hesaplanır?",
        "expected_madde": "İK m.41",
        "expected_kanun": "4857",
        "verified_claim": (
            "Fazla çalışma için işçiye normal saatlik ücretin "
            "yüzde elli zamlı ödeme yapılır (İK m.41)."
        ),
        "fabricated_claim_no": "8888",
    },
    {
        "id": "Y-13HD-2018-789",
        "domain": "tuketici",
        "question": "Ayıplı malı geri verme hakkım ne kadar süre?",
        "expected_madde": "TKHK m.12",
        "expected_kanun": "6502",
        "verified_claim": (
            "Tüketici, ayıplı maldan doğan hakkını teslim tarihinden "
            "itibaren 2 yıl içinde kullanabilir (TKHK m.12)."
        ),
        "fabricated_claim_no": "7777",
    },
    {
        "id": "Y-15HD-2017-321",
        "domain": "tuketici",
        "question": "Mesafeli satışta cayma hakkı kaç gün?",
        "expected_madde": "TKHK m.48",
        "expected_kanun": "6502",
        "verified_claim": (
            "Mesafeli satışlarda tüketici 14 gün içinde "
            "hiçbir gerekçe göstermeksizin cayma hakkına sahiptir (TKHK m.48)."
        ),
        "fabricated_claim_no": "6666",
    },
    {
        "id": "Y-6HD-2021-111",
        "domain": "kira",
        "question": "Kiracıyı tahliye için ihtar süresi ne kadar?",
        "expected_madde": "TBK m.315",
        "expected_kanun": "6098",
        "verified_claim": (
            "Kira ödenmemesi durumunda en az 30 günlük "
            "ihtar verilmesi gerekir (TBK m.315)."
        ),
        "fabricated_claim_no": "5555",
    },
    {
        "id": "Y-3HD-2022-222",
        "domain": "kira",
        "question": "Kira artışı için TÜFE oranı uygulanır mı?",
        "expected_madde": "TBK m.344",
        "expected_kanun": "6098",
        "verified_claim": (
            "Konut kiralarında bir yıllık kira artışı TÜFE "
            "oranını aşamaz (TBK m.344)."
        ),
        "fabricated_claim_no": "4444",
    },
    {
        "id": "Y-12HD-2020-333",
        "domain": "icra",
        "question": "İcra takibine itiraz süresi nedir?",
        "expected_madde": "İİK m.62",
        "expected_kanun": "2004",
        "verified_claim": (
            "İcra emrinin tebliğinden itibaren 7 gün içinde "
            "itiraz edilebilir (İİK m.62)."
        ),
        "fabricated_claim_no": "3333",
    },
    {
        "id": "D-4D-2019-444",
        "domain": "vergi",
        "question": "Vergi mahkemesine başvuru süresi kaç gün?",
        "expected_madde": "İYUK m.7",
        "expected_kanun": "2577",
        "verified_claim": (
            "İdari işleme karşı vergi mahkemesinde 30 gün içinde "
            "dava açılması gerekir (İYUK m.7)."
        ),
        "fabricated_claim_no": "2222",
    },
]


@pytest.mark.parametrize("case", YARGITAY_LANDMARK_CASES, ids=lambda c: c["id"])
def test_landmark_verified_claim_passes_rules(case: dict) -> None:
    """Her landmark için verified_claim layer1_rules geçmeli."""
    claim = Claim(
        text=case["verified_claim"], cite_ids=[],
        verified=False, verify_score=0.0, verify_reason="",
    )
    ok, msg = layer1_rules(claim)
    assert ok, f"{case['id']}: rules failed → {msg}"


@pytest.mark.parametrize("case", YARGITAY_LANDMARK_CASES, ids=lambda c: c["id"])
def test_landmark_fabricated_madde_caught_by_rules_or_fuzzy(case: dict) -> None:
    """Uydurma madde no (9999, 8888 vb.) verify katmanları ile reject olmalı."""
    fabricated_text = (
        f"{case['expected_madde'].split(' m.')[0]} m.{case['fabricated_claim_no']} "
        "uyarınca bu hakkı kullanabilirsiniz."
    )
    claim = Claim(
        text=fabricated_text, cite_ids=[],
        verified=False, verify_score=0.0, verify_reason="",
    )
    refs = [Citation(
        source_id=case["id"], doc_type="law",
        title=case["expected_madde"],
        snippet=case["verified_claim"], url="x",
        score=0.9,
    )]
    # Rules might pass (format valid 9999 < 99999), but fuzzy should fail
    rules_ok, _ = layer1_rules(claim)
    fuzzy_score, _, _ = layer2_fuzzy(claim, refs)
    # Either rules reject (madde no out of range) OR fuzzy below support
    assert (not rules_ok) or fuzzy_score < FUZZY_SUPPORT_THRESHOLD, (
        f"{case['id']}: fabricated madde {case['fabricated_claim_no']} "
        f"slipped through (rules={rules_ok}, fuzzy={fuzzy_score:.2f})"
    )


def test_domain_distribution_balanced() -> None:
    """Landmark setinde 4 alan eşit dağılmalı (2 vaka/alan)."""
    domains = [c["domain"] for c in YARGITAY_LANDMARK_CASES]
    assert domains.count("isHukuku") == 2
    assert domains.count("tuketici") == 2
    assert domains.count("kira") == 2
    assert domains.count("icra") + domains.count("vergi") == 2


def test_all_landmarks_have_required_fields() -> None:
    """Her landmark fixture şema bütünlüğü."""
    required = {"id", "domain", "question", "expected_madde",
                "expected_kanun", "verified_claim", "fabricated_claim_no"}
    for case in YARGITAY_LANDMARK_CASES:
        missing = required - set(case.keys())
        assert not missing, f"{case.get('id')}: missing {missing}"


def test_nli_threshold_in_safe_range() -> None:
    """W4.5 sonu: NLI threshold makul aralıkta tutulmalı.

    0.50'in altı çok agresif (Türkçe XNLI false-pos), 0.85'in üstü pratik
    olarak hiç veto etmiyor. 0.65-0.80 sweet spot.
    """
    assert 0.50 <= NLI_CONTRADICTION_THRESHOLD <= 0.85
