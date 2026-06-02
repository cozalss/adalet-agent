"""agents/risk_guard.py — SIFIR HALÜSİNASYON veto regresyon testleri.

Kullanıcı direktifi (2026-05-30): "2 yıl çalıştım, kıdem tazminatım ne kadar?"
sorusunun GERÇEK halüsinasyonlu cevabı sabit regresyon vakası olsun.
"""

from __future__ import annotations

from agents.risk_guard import (
    fabricated_citation_claims,
    fabricated_law_names,
    negative_eligibility_claims,
    verify_risk_veto,
)

# Gerçek Qwen 14B çıktısı (2026-05-30) — üç ölümcül hata içeriyor.
REAL_HALLUCINATED_ANSWER = (
    "Kısa cevap: İşten çıkarıldığınızda kıdem tazminatınızın miktarı çalışma "
    "sürenize göre belirlenir. [src: m-EIK-14] Ancak, belirttiğiniz 2 yıl süre, "
    "kanunlarda açıkça belirtilen minimum çalışma süresini karşılamıyor. [src: m-IK-21]\n"
    "Dayanak: İşçilik Kanunu'nun 21. maddesi işverenin işçiyi işe başlatması "
    "gerektiğini belirtir. [src: m-EIK-14] Ancak bu süre 5 yılın altında ise "
    "tazminat verilmeyebilir. [src: h-100553800-c4]"
)


# --- REGRESYON: üç ölümcül hata geçememeli ---

def test_regression_two_year_ineligibility_blocked():
    """'2 yıl minimum süreyi karşılamıyor' veto'yu tetiklemeli."""
    blocked, reasons = verify_risk_veto(REAL_HALLUCINATED_ANSWER)
    assert blocked is True
    # Süre-reddi gerekçesi olmalı
    assert any("hak-reddi" in r for r in reasons)


def test_regression_five_year_fabricated_threshold_blocked():
    """'5 yıl altında verilmeyebilir' uydurma eşik yakalanmalı."""
    flags = negative_eligibility_claims(
        "Bu süre 5 yılın altında ise tazminat verilmeyebilir.")
    assert len(flags) >= 1


def test_regression_iscilik_kanunu_blocked():
    """'İşçilik Kanunu' uydurma kanun adı yakalanmalı."""
    assert fabricated_law_names(REAL_HALLUCINATED_ANSWER) == ["İşçilik Kanunu"]


def test_regression_full_answer_is_rejected():
    """Gerçek halüsinasyonlu cevap BLOKLANMALI (fail-closed reject)."""
    blocked, reasons = verify_risk_veto(REAL_HALLUCINATED_ANSWER)
    assert blocked is True
    # En az iki ayrı risk (uydurma kanun + hak-reddi)
    assert len(reasons) >= 2


# --- FALSE-POSITIVE: doğru cevaplar bloklanMAMALI ---

def test_correct_eligibility_statement_not_blocked():
    """'Kıdem için en az 1 yıl gerekir' DOĞRU bilgi — bloklanmamalı."""
    good = "Kıdem tazminatı için işyerinde en az 1 yıl çalışmış olmak gerekir [src: m-IK-14]."
    blocked, reasons = verify_risk_veto(good)
    assert blocked is False, f"doğru cevap yanlışlıkla bloklandı: {reasons}"


def test_positive_eligibility_not_blocked():
    """'2 yıl çalıştınız, hak kazanırsınız' DOĞRU pozitif sonuç — bloklanmamalı."""
    good = ("İki yıl çalıştığınız için kıdem tazminatına hak kazanırsınız "
            "[src: m-IK-14]. Tutar son brüt ücretiniz üzerinden hesaplanır.")
    blocked, _ = verify_risk_veto(good)
    assert blocked is False


def test_real_law_name_not_flagged():
    good = "İş Kanunu madde 14 uyarınca kıdem tazminatı ödenir [src: m-IK-14]."
    assert fabricated_law_names(good) == []


def test_clean_answer_no_veto():
    good = ("Kısa cevap: İade hakkınız bulunmaktadır [src: m-TKHK-11]. "
            "Satıcıya başvurarak onarım veya değişim talep edebilirsiniz [src: m-TKHK-11].")
    blocked, reasons = verify_risk_veto(good)
    assert blocked is False
    assert reasons == []


# --- İmkânsız mahkeme dairesi atfı (yeni detektör) ---

def test_fabricated_high_chamber_blocked():
    """'99. Hukuk Dairesi' imkânsız daire — veto'yu tetiklemeli."""
    bad = "Yargıtay 99. Hukuk Dairesi kararına göre talebiniz haklıdır [src: h-123-c1]."
    assert len(fabricated_citation_claims(bad)) == 1
    blocked, reasons = verify_risk_veto(bad)
    assert blocked is True
    assert any("dairesi atfı" in r for r in reasons)


def test_danistay_high_dava_dairesi_flagged():
    """Danıştay 45. Dava Dairesi — imkânsız, bayraklanmalı."""
    assert len(fabricated_citation_claims("Danıştay 45. Dava Dairesi kararı")) == 1


def test_real_chamber_not_flagged():
    """Gerçek daireler (9. Hukuk / 12. Ceza) bloklanMAMALI (FP guard — kritik)."""
    for good in (
        "Yargıtay 9. Hukuk Dairesi içtihadı bu yöndedir [src: h-555-c1].",
        "Yargıtay 12. Ceza Dairesi kararı [src: h-777-c2].",
        "Danıştay 10. Dava Dairesi [src: h-888-c1].",
    ):
        assert fabricated_citation_claims(good) == [], f"gerçek daire bayraklandı: {good}"
        assert verify_risk_veto(good)[0] is False
