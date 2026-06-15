"""agents/risk_guard.py — SIFIR HALÜSİNASYON veto regresyon testleri.

Kullanıcı direktifi (2026-05-30): "2 yıl çalıştım, kıdem tazminatım ne kadar?"
sorusunun GERÇEK halüsinasyonlu cevabı sabit regresyon vakası olsun.
"""

from __future__ import annotations

from agents.risk_guard import (
    fabricated_citation_claims,
    fabricated_eligibility_threshold,
    fabricated_law_names,
    implausible_article_numbers,
    negative_eligibility_claims,
    verify_risk_veto,
)


def test_implausible_article_vetoed():
    """'madde 5000' imkânsız (TMK ~1030 max) → veto (denetim 2026-06-04: eval→production)."""
    assert implausible_article_numbers("İş Kanunu madde 5000 uyarınca haklısınız.") == ["madde 5000"]
    blocked, reasons = verify_risk_veto("Somut olayda madde 5000 geçerlidir [src: m-X-5000].")
    assert blocked
    assert any("madde numarası" in r for r in reasons)


def test_real_article_number_not_vetoed():
    """Gerçek yüksek madde (TMK madde 1029 ≤ 1100) bloklanMAMALI (FP guard — kritik)."""
    assert implausible_article_numbers("Türk Medeni Kanunu madde 1029 taşkın yapıyı düzenler.") == []
    blocked, _ = verify_risk_veto("Türk Medeni Kanunu madde 1029 uygulanır [src: m-TMK-1029].")
    assert blocked is False

# --- FABRİKE-eşik (kaynak-temelli, deterministik TRUE-vs-FABRİKE ayrımı) ---


def test_fabricated_threshold_flags_ungrounded():
    """Kaynakta OLMAYAN eşik ('5 yıldan az verilmez', kaynak '1 yıl') → FABRİKE."""
    flags = fabricated_eligibility_threshold(
        "5 yıldan az çalıştıysanız kıdem tazminatı verilmez.",
        ["Kıdem için en az 1 yıl çalışma şartı aranır (m.14)."],
    )
    assert flags  # işaretlenmeli


def test_fabricated_threshold_allows_grounded_true():
    """Kaynakta OLAN eşik ('1 yılın altında kazanamaz', kaynak '1 yıl') → DOĞRU, vetolanmaz."""
    flags = fabricated_eligibility_threshold(
        "Bir yılın altında çalıştıysanız kıdem tazminatına hak kazanamazsınız.",
        ["Kıdem tazminatı için işçinin en az 1 yıl çalışmış olması gerekir."],
    )
    assert flags == []  # DOĞRU bilgilendirme — false-positive YOK


def test_fabricated_threshold_no_sources_silent():
    """Kaynak yoksa temellendirme yapılamaz → sessiz (baseline güvenli)."""
    assert fabricated_eligibility_threshold("5 yıldan az ise verilmez.", []) == []


def test_fabricated_threshold_eval_precision_perfect():
    """Adversarial gold set: precision=1.0 (DOĞRU/temiz cevap ASLA yanlış-işaretlenmez)
    + recall yüksek. 'Sıfır halüsinasyon' kanıtı + valid cevabı bozmama garantisi."""
    from eval.eligibility_eval import evaluate, load_gold
    res = evaluate(load_gold())
    assert res["precision"] == 1.0, "FALSE-POSITIVE = valid cevabı bozar (kabul edilemez)"
    assert res["recall"] >= 0.85
    assert res["n"] >= 16


def test_verify_veto_relaxes_grounded_true_with_sources():
    """source_texts verilince kaynakta-temelli DOĞRU eşik MUAF (vetolanmaz) → flakiness fix."""
    blocked, _ = verify_risk_veto(
        "Bir yılın altında çalıştıysanız kıdem tazminatına hak kazanamazsınız.",
        source_texts=["Kıdem için işçinin en az 1 yıl çalışmış olması gerekir."],
    )
    assert not blocked


def test_verify_veto_blocks_fabricated_threshold_with_sources():
    """source_texts verilince bile FABRİKE (kaynakta-olmayan) eşik → VETO (kırmızı çizgi)."""
    blocked, _ = verify_risk_veto(
        "5 yıldan az çalıştıysanız kıdem tazminatı verilmez.",
        source_texts=["Kıdem için en az 1 yıl çalışma şartı aranır."],
    )
    assert blocked


def test_verify_veto_no_sources_baseline_blocks():
    """source_texts YOKsa baseline: süre/eşik hak-reddi veto (muhafazakâr, geriye-uyumlu)."""
    blocked, _ = verify_risk_veto("Bir yılın altında hak kazanamazsınız.")
    assert blocked


def test_grounded_scoping_ignores_unrelated_snippet_threshold():
    """ÇAPRAZ-KONTAMİNASYON (denetim 2026-06-04): ilgisiz bir snippet'teki süre
    ('zamanaşımı 5 yıl') uydurma bir hak-reddi eşiğini ('5 yıl altında') AKLAYAMAZ.
    Grounding küresel havuz değil, asgari-gereklilik bağlamı taşıyan snippet'lerden gelir."""
    sources = [
        "Kıdem tazminatı için işçinin en az 1 yıl çalışmış olması gerekir.",
        "Alacak için zamanaşımı süresi 5 yıldır.",  # ilgisiz — gereklilik bağlamı YOK
    ]
    answer = "5 yıldan az çalıştıysanız kıdem tazminatına hak kazanamazsınız."
    assert fabricated_eligibility_threshold(answer, sources), "5 yıl FABRİKE kalmalı"
    blocked, _ = verify_risk_veto(answer, source_texts=sources)
    assert blocked, "ilgisiz snippet veto'dan kaçırmamalı (kırmızı çizgi)"


def test_grounded_true_still_exempt_with_requirement_snippet():
    """Regresyon: gereklilik bağlamlı snippet kaynaktaki DOĞRU eşiği aklamaya devam eder."""
    sources = ["Kıdem için işçinin en az 1 yıl çalışmış olması gerekir."]
    answer = "Bir yılın altında çalıştıysanız kıdem tazminatına hak kazanamazsınız."
    assert fabricated_eligibility_threshold(answer, sources) == []  # DOĞRU bilgilendirme
    blocked, _ = verify_risk_veto(answer, source_texts=sources)
    assert not blocked

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


def test_positive_met_requirement_not_vetoed():
    """OLUMLU 'şartı karşılamış olabilirsiniz' (hak DOĞAR) vetolanMAMALI (gerçek-LLM 2026-06-04
    bug: 'karşılamış' yanlışlıkla 'karşılamıyor' gibi yakalanıp tüm cevap reddediliyordu)."""
    for good in (
        "2 yıl çalıştığınız için en az 1 yıllık kıdem şartını karşılamış olabilirsiniz [src: m-IK-14].",
        "Belirttiğiniz süre asgari koşulu sağlamış görünüyor [src: m-IK-14].",
    ):
        blocked, reasons = verify_risk_veto(good)
        assert blocked is False, f"olumlu uygunluk yanlış vetolandı: {reasons}"


def test_negative_not_met_still_vetoed():
    """OLUMSUZ 'karşılamıyor/sağlamıyor' HÂLÂ veto (kırmızı çizgi korunur)."""
    for bad in (
        "6 aylık süreniz 1 yıllık kıdem şartını karşılamıyor.",
        "Süreniz asgari koşulu sağlamıyor.",
    ):
        assert verify_risk_veto(bad)[0] is True, f"olumsuz hak-reddi veto edilmedi: {bad}"


# --- POZİTİF fabrike çıkarım (sayısal eşik-altı hak-tanıma, FAZ 1.3) ---

def test_positive_below_threshold_fabrication_vetoed():
    """'6 ay → kıdem alırsınız' (kaynak min 1 yıl) → süre-eşik-altı FABRİKE → veto.

    Negatif yol kaçırıyordu (grant verb, denial değil; ölçüldü 2026-06-12)."""
    src = ["Kıdem tazminatı için işçinin en az 1 yıl çalışmış olması gerekir."]
    for bad in (
        "Altı ay çalıştıysanız kıdem tazminatına hak kazanırsınız.",
        "Üç ay çalışan işçi kıdem tazminatı talep edebilir.",
    ):
        blocked, reasons = verify_risk_veto(bad, source_texts=src)
        assert blocked is True, f"eşik-altı pozitif fabrike kaçtı: {bad}"
        assert any("fabrike hak-tanıma" in r for r in reasons)


def test_positive_above_threshold_not_vetoed():
    """'2 yıl → hak kazanırsınız' (≥ min 1 yıl) DOĞRU pozitif → bloklanmamalı (FP guard)."""
    src = ["Kıdem tazminatı için işçinin en az 1 yıl çalışmış olması gerekir."]
    for good in (
        "İki yıl çalıştığınız için kıdem tazminatına hak kazanırsınız.",
        "Bir yıl dolduran işçi kıdem tazminatına hak kazanır.",
    ):
        blocked, reasons = verify_risk_veto(good, source_texts=src)
        assert blocked is False, f"doğru pozitif yanlış vetolandı: {good} → {reasons}"


def test_positive_fabrication_silent_without_source_minimum():
    """Kaynak gereklilik-eşiği yoksa pozitif detektör SESSİZ (fail-open, FP koruması)."""
    blocked, _ = verify_risk_veto(
        "Altı ay çalıştıysanız kıdem tazminatına hak kazanırsınız.",
        source_texts=["Kıdem tazminatı işçinin haklarındandır."],  # eşik YOK
    )
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
