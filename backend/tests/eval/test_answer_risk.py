"""eval/answer_risk.py birim testleri — gerçek gözlemlenmiş halüsinasyonlarla."""

from __future__ import annotations

from eval.answer_risk import (
    duration_eligibility_claims,
    fabricated_law_names,
    implausible_article_numbers,
    measure_risk,
    unsourced_legal_claims,
)

# --- İmkânsız madde numarası (ölçüm-amaçlı) ---

def test_implausible_article_flagged():
    assert len(implausible_article_numbers("Bu durumda madde 5000 uygulanır.")) == 1


def test_real_article_not_flagged():
    # TMK ~1030 madde — en büyük TR kanunu; gerçek madde no bayraklanmaz (FP guard).
    assert implausible_article_numbers("İş Kanunu madde 14 uyarınca tazminat ödenir.") == []
    assert implausible_article_numbers("Türk Medeni Kanunu madde 1030 hükmü.") == []

# --- Süre-uygunluk iddiaları (gerçek Qwen hatası 2026-05-30) ---

def test_detects_wrong_duration_eligibility_claim():
    # GERÇEK HALÜSİNASYON: 2 yıl kıdem için yeterli (md.14 min 1 yıl) ama model "yetersiz" demiş
    bad = "Belirttiğiniz 2 yıllık süre, kanunlara göre kıdem tazminatı için yeterli değildir."
    flags = duration_eligibility_claims(bad)
    assert len(flags) == 1


def test_detects_minimum_duration_claim():
    txt = "Kıdem tazminatı için en az 1 yıl çalışmış olmak gerekir."
    assert len(duration_eligibility_claims(txt)) == 1


def test_no_flag_when_no_eligibility_judgment():
    # Süre var ama uygunluk yargısı yok → bayraklanmaz
    txt = "Kira sözleşmesi 1 yıl süreyle yapılmıştır."
    assert len(duration_eligibility_claims(txt)) == 0


# --- Uydurma kanun adları (gerçek Qwen hatası) ---

def test_detects_fabricated_iscilik_kanunu():
    # GERÇEK: model "İşçilik Kanunu" uydurdu (gerçek: İş Kanunu)
    bad = "İşçilik Kanunu'na göre işveren tazminat ödemek zorundadır."
    assert fabricated_law_names(bad) == ["İşçilik Kanunu"]


def test_real_law_name_not_flagged():
    good = "İş Kanunu madde 14 uyarınca kıdem tazminatı ödenir."
    assert fabricated_law_names(good) == []


def test_detects_fabricated_tuketicilik():
    bad = "Tüketicilik Kanunu kapsamında iade hakkınız vardır."
    assert len(fabricated_law_names(bad)) == 1


# --- Kaynaksız hukuki iddia ---

def test_detects_unsourced_legal_claim():
    txt = "İşveren kıdem tazminatı ödemek zorundadır."  # iddia var, [src:] yok
    assert len(unsourced_legal_claims(txt)) == 1


def test_sourced_claim_not_flagged():
    txt = "İşveren kıdem tazminatı ödemek zorundadır [src: m-IK-14]."
    assert len(unsourced_legal_claims(txt)) == 0


def test_boilerplate_not_flagged_as_unsourced():
    txt = "Bu cevap hukuki tavsiye değildir, bir avukata danışın."
    assert len(unsourced_legal_claims(txt)) == 0


def test_detects_unsourced_varied_claim_verbs():
    """Genişletilmiş marker'lar: farklı fiil/kalıplı kaynaksız iddialar da yakalanır."""
    for txt in (
        "Tahliye talep etmeniz mümkün değildir.",          # talep et + mümkün değil
        "Bu durumda kira artışına itiraz hakkınız doğmaz.",  # hak doğ
        "İade ve bedel talep etme hakkınız bulunmaktadır.",  # talep et / hakkınız
        "İdari işlem iptal edilir ve yeniden değerlendirilir.",  # iptal ed
    ):
        assert len(unsourced_legal_claims(txt)) >= 1, f"yakalanmadı: {txt}"


def test_varied_claims_sourced_not_flagged():
    """Aynı kalıplar KAYNAKLI olunca bayraklanMAMALI (FP guard)."""
    for txt in (
        "Tahliye talep etmeniz mümkün değildir [src: m-TBK-350].",
        "İtiraz hakkınız doğmaz [src: m-TBK-344].",
    ):
        assert unsourced_legal_claims(txt) == [], f"kaynaklı iddia bayraklandı: {txt}"


# --- measure_risk orkestratör ---

def test_measure_risk_aggregates_all():
    # Gerçek isHukuku cevabının kısaltılmış hali — 3 risk türü
    bad = (
        "İşçilik Kanunu'na göre 2 yıllık süre kıdem tazminatı için yeterli değildir. "
        "İşveren tazminat ödemek zorundadır."
    )
    risk = measure_risk(bad)
    assert risk["fabricated_laws"] >= 1
    assert risk["duration_claims"] >= 1
    assert risk["has_risk"] is True


def test_clean_answer_no_risk():
    good = (
        "**Kısa cevap:** İade hakkınız bulunmaktadır [src: m-TKHK-11]. "
        "Bu cevap hukuki tavsiye değildir, bir avukata danışın."
    )
    risk = measure_risk(good)
    assert risk["has_risk"] is False
