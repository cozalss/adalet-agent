"""Policy engine — cevap-yolu kararı (saf fonksiyon, LLM yok).

decide_path bir state dict'inden deterministik bir karar üretir. Bu testler
her dalı + _facts_sufficient şema mantığını doğrudan (graph/LLM olmadan) doğrular.
"""

from __future__ import annotations

import pytest

from agents.policy import (
    CLARIFY_MARKER,
    MAX_CLARIFICATION_ROUNDS,
    MIN_FACTS_FOR_ANSWER,
    REQUIRED_FACTS,
    _facts_sufficient,
    decide_path,
)

# --- decide_path: intent passthrough ---

def test_smalltalk_intent_returns_chat():
    # Hukuki-olmayan → genel sohbet (chat node, Qwen doğal cevap), eski "smalltalk" değil.
    assert decide_path({"response_intent": "smalltalk", "domain": "unknown"}) == "chat"


def test_out_of_scope_sensitive_returns_chat():
    # Ceza/aile kapsam-dışı → chat node (system-prompt detaylı tavsiye vermez, avukat önerir).
    state = {"response_intent": "out_of_scope_sensitive", "domain": "unknown"}
    assert decide_path(state) == "chat"


def test_unknown_domain_returns_chat():
    # Belirsiz/genel soru → chat node (doğal cevap), eski soğuk "redirect" değil.
    state = {"response_intent": "legal_answer", "domain": "unknown", "question": "fransa başkenti ne"}
    assert decide_path(state) == "chat"


# --- decide_path: clarify vs answer ---

def test_kira_with_no_facts_returns_clarify():
    state = {"response_intent": "legal_answer", "domain": "kira", "case_facts": {}}
    assert decide_path(state) == "clarify"


def test_kira_with_sufficient_facts_returns_answer():
    # kira: "olay" gerekli + en az 2 olgu.
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {"olay": "depozito iade edilmiyor", "tutar": "5000 TL"},
    }
    assert decide_path(state) == "answer"


def test_kira_with_only_one_fact_returns_clarify():
    # olay var ama tek olgu < MIN_FACTS_FOR_ANSWER["kira"]=2.
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {"olay": "depozito iade edilmiyor"},
    }
    assert decide_path(state) == "clarify"


def test_tuketici_with_single_fact_returns_answer():
    # tüketici min=1 → olay + 1 olgu yeterli.
    state = {
        "response_intent": "legal_answer",
        "domain": "tuketici",
        "case_facts": {"olay": "ayıplı ürün"},
    }
    assert decide_path(state) == "answer"


def test_missing_case_facts_key_treated_as_empty():
    # Genel-soru kalıbı yok + olgu yok → durumsal şikâyet kabul → clarify.
    state = {"response_intent": "legal_answer", "domain": "kira", "question": "depozitomu alamıyorum"}
    assert decide_path(state) == "clarify"


def test_general_question_answers_even_without_facts():
    # "nasıl hesaplanır?" gibi tanımsal bilgi sorusu olgu-yok olsa da cevaplanır.
    state = {
        "response_intent": "legal_answer",
        "domain": "isHukuku",
        "case_facts": {},
        "question": "Kıdem tazminatı nasıl hesaplanır?",
    }
    assert decide_path(state) == "answer"


def test_situational_complaint_without_facts_clarifies():
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {},
        "question": "kira depozitomu ev sahibi geri vermiyor",
    }
    assert decide_path(state) == "clarify"


# --- decide_path: loop guards ---

def test_round_at_limit_forces_answer():
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {},
        "clarification_round": MAX_CLARIFICATION_ROUNDS,
    }
    assert decide_path(state) == "answer"


def test_user_already_answered_marker_forces_answer():
    # Önceki asistan turu netleştirme sorusuysa (marker), bu tur cevaptır.
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {},
        "chat_history": [
            {"role": "user", "content": "depozitomu alamıyorum"},
            {"role": "assistant", "content": f"{CLARIFY_MARKER}\n\n1. Sözleşme bitti mi?"},
        ],
    }
    assert decide_path(state) == "answer"


def test_history_without_marker_does_not_force_answer():
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "case_facts": {},
        "chat_history": [
            {"role": "assistant", "content": "Merhaba, nasıl yardımcı olabilirim?"},
        ],
    }
    assert decide_path(state) == "clarify"


# --- _facts_sufficient unit ---

def test_facts_sufficient_requires_required_keys():
    # kira "olay" gerektirir; olay yoksa yetersiz.
    assert _facts_sufficient("kira", {"tutar": "5000", "tarih": "2026"}) is False


def test_facts_sufficient_respects_min_count():
    assert _facts_sufficient("kira", {"olay": "x"}) is False           # 1 < 2
    assert _facts_sufficient("kira", {"olay": "x", "sure": "1 yıl"}) is True


def test_facts_sufficient_ignores_blank_values():
    assert _facts_sufficient("tuketici", {"olay": "   "}) is False


def test_unknown_domain_in_schema_defaults_min_one():
    # Şemada olmayan domain → required boş, min 1 (savunmacı default).
    assert _facts_sufficient("xyz", {"olay": "bir olay"}) is True
    assert _facts_sufficient("xyz", {}) is False


# --- schema sanity ---

def test_all_valid_domains_have_schema_entries():
    domains = {"tuketici", "isHukuku", "kira", "icra", "trafik", "vergi", "tapu", "idari"}
    assert domains <= set(REQUIRED_FACTS)
    assert domains <= set(MIN_FACTS_FOR_ANSWER)


# --- iter8: over-clarification fix — doğal "nasıl/ne olur/haklarım/edebilir mi" → answer ---

@pytest.mark.parametrize("domain,question", [
    ("isHukuku", "işten haksız yere çıkarıldım hangi haklarım var"),
    ("trafik", "kırmızı ışık cezasına nasıl itiraz edebilirim"),
    ("vergi", "emlak vergimi geç ödedim gecikme cezası ne olur"),
    ("idari", "belediyenin verdiği para cezasına itiraz edebilir miyim"),
])
def test_natural_info_questions_answer_not_overclarify(domain, question):
    """Ölçülen over-clarification: bilgi/nasıl sorusu olgu-eksik olsa da cevaplanır
    (clarify değil) — situational+general dahil (line 120 _is_general_question)."""
    state = {"response_intent": "legal_answer", "domain": domain,
             "case_facts": {}, "question": question}
    assert decide_path(state) == "answer"


def test_bare_situational_complaint_still_clarifies():
    """Yalın durum şikâyeti (bilgi/nasıl kalıbı YOK) hâlâ clarify (regresyon yok)."""
    for q in ("depozitomu alamıyorum", "kira çok yüksek geldi"):
        state = {"response_intent": "legal_answer", "domain": "kira",
                 "case_facts": {}, "question": q}
        assert decide_path(state) == "clarify"


def test_bare_question_words_answer_iter11():
    """iter11: bare soru-kelimeleri (nasıl/hangi/...) over-clarification'ı keser
    ('uzlaşma nasıl olur' clarify'a düşüyordu)."""
    for dom, q in [("vergi", "vergi ziyaı cezasında uzlaşma nasıl olur"),
                   ("kira", "kira davası için hangi mahkemeye başvurmalıyım"),
                   ("idari", "bu karara neden itiraz edemiyorum")]:
        assert decide_path({"response_intent": "legal_answer", "domain": dom,
                            "case_facts": {}, "question": q}) == "answer"


# --- ayırt edici (discriminator) kapı: tahliye sebebi ---

def test_kira_landlord_eviction_clarifies_even_when_phrased_general():
    """Kullanıcının asıl şikâyeti: 'kiracımı çıkaramıyorum ne yapabilirim' gibi
    GENEL kalıpta bile, ayırt edici tahliye SEBEBİ bilinmeden sığ cevaba düşüyordu.
    Artık önce sebebi sor (discriminator kapı, general/sufficient'tan önce)."""
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "question": "kiracımı çıkaramıyorum ne yapabilirim",
        "case_facts": {"olay": "kiracıyı çıkaramıyorum", "taraf": "ev sahibi"},
    }
    assert decide_path(state) == "clarify"


def test_kira_eviction_reason_only_asks_reason_specific_followup():
    """Round-2 dallanma: sebep (ihtiyaç) verildi ama sebebe-özel belirleyici bilgi
    (kim oturacak / sürekli mi) yok → follow-up sor ('tam akış')."""
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "question": "kiracımı kendi ihtiyacım için çıkarmak istiyorum nasıl yaparım",
        "case_facts": {"olay": "kiracıyı ihtiyaç nedeniyle çıkarmak istiyorum"},
    }
    assert decide_path(state) == "clarify"


def test_kira_eviction_full_picture_answers_without_overasking():
    """Sebep + sebebe-özel ayrıntı tek mesajda verildi → follow-up sorma, cevapla."""
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "question": (
            "kiracımı kendi ihtiyacım için çıkarmak istiyorum; eşim ve çocuğumla biz "
            "oturacağız, ihtiyaç sürekli"
        ),
        "case_facts": {"olay": "kiracıyı ihtiyaç nedeniyle çıkarmak; eşim çocuğum oturacak sürekli"},
    }
    assert decide_path(state) == "answer"


def test_eviction_round2_asks_reason_specific_followup_across_turns():
    """Round-1'de sebep soruldu, kullanıcı 'ihtiyaç' dedi (geçmişte 1 marker) →
    round-2 sebebe-özel soru sor (marker olsa da follow-up beklediği için cevaba düşmez)."""
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "question": "kendi ihtiyacım için lazım",
        "case_facts": {"olay": "kiracıyı çıkaramıyorum kendi ihtiyacım için lazım"},
        "chat_history": [
            {"role": "user", "content": "kiracımı çıkaramıyorum"},
            {"role": "assistant", "content": f"{CLARIFY_MARKER} kiracıyı hangi sebeple çıkarmak istiyorsunuz?"},
        ],
    }
    assert decide_path(state) == "clarify"


def test_eviction_hard_cap_two_rounds_then_answers():
    """Sert tur sınırı: iki clarify turundan sonra (zincir=2) sebebe-özel bilgi hâlâ
    eksik olsa bile cevapla — sonsuz soru-sorma döngüsü imkânsız."""
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "question": "tam bilmiyorum",
        "case_facts": {"olay": "kiracıyı çıkaramıyorum kendi ihtiyacım"},
        "chat_history": [
            {"role": "user", "content": "kiracımı çıkaramıyorum"},
            {"role": "assistant", "content": f"{CLARIFY_MARKER} hangi sebeple çıkarmak istiyorsunuz?"},
            {"role": "user", "content": "ihtiyacım için"},
            {"role": "assistant", "content": f"{CLARIFY_MARKER} konutta kim oturacak?"},
        ],
    }
    assert decide_path(state) == "answer"


def test_freetext_reason_round2_clarifies_like_chip():
    """Kullanıcı şıkka tıklamak yerine sebebi KENDİ yazdı ('kira vermiyor') →
    yine round-2 sebebe-özel soru sorulur (chip ile aynı akış)."""
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "question": "kira vermiyor",
        "case_facts": {"olay": "kiracıyı çıkaramıyorum kira vermiyor"},
        "chat_history": [
            {"role": "user", "content": "kiracımı çıkaramıyorum"},
            {"role": "assistant", "content": f"{CLARIFY_MARKER} hangi sebeple çıkarmak istiyorsunuz?"},
        ],
    }
    assert decide_path(state) == "clarify"


def test_unrecognized_freetext_reason_answers_no_loop():
    """Tanınmayan serbest-metin sebep (round-1 sonrası) → DÖNGÜYE girmez, best-effort cevaplar
    (chip'imiz işine yaramayan kullanıcı serbest yazsa bile takılı kalmaz)."""
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "question": "durumum biraz karışık",
        "case_facts": {"olay": "kiracıyı çıkaramıyorum durumum biraz karışık"},
        "chat_history": [
            {"role": "user", "content": "kiracımı çıkaramıyorum"},
            {"role": "assistant", "content": f"{CLARIFY_MARKER} hangi sebeple çıkarmak istiyorsunuz?"},
        ],
    }
    assert decide_path(state) == "answer"


def test_icra_situation_asks_stance_even_when_phrased_general():
    """Karşılaşılan icra olayı + duruş belirsiz → 'ne yapmalıyım' genel kalıba rağmen
    önce DURUŞU (itiraz/kabul/alacaklı) sor — cevabı tümden değiştirir."""
    state = {
        "response_intent": "legal_answer",
        "domain": "icra",
        "question": "hakkımda icra takibi başlatıldı ne yapmalıyım",
        "case_facts": {"olay": "icra takibi başlatıldı"},
    }
    assert decide_path(state) == "clarify"


def test_icra_general_howto_answers_no_overclarify():
    """Genel/tanımsal icra sorusu (karşılaşılan olay yok) → answer (over-clarify YOK)."""
    for q in ("icra takibi nasıl açılır", "ödeme emrine itiraz nasıl yapılır"):
        state = {"response_intent": "legal_answer", "domain": "icra",
                 "case_facts": {}, "question": q}
        assert decide_path(state) == "answer", q


def test_icra_stance_given_round2_followup():
    """Kullanıcı duruşu verdi (itiraz) → round-2 duruşa-özel soru (süre/itiraz kapsamı)."""
    state = {
        "response_intent": "legal_answer",
        "domain": "icra",
        "question": "borca itiraz edeceğim",
        "case_facts": {"olay": "hakkımda icra takibi başlatıldı borca itiraz edeceğim"},
        "chat_history": [
            {"role": "user", "content": "icra geldi"},
            {"role": "assistant", "content": f"{CLARIFY_MARKER} icra sürecinde durumunuz ne?"},
        ],
    }
    assert decide_path(state) == "clarify"


def test_new_topic_after_completed_clarify_can_clarify_again():
    """Tamamlanmış bir clarify+cevap zincirinden SONRA yeni durumsal soru → zincir
    kırıldığı için (araya normal cevap girdi) yine netleştirilebilir (zincir=0)."""
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "question": "depozitomu alamıyorum",
        "case_facts": {},
        "chat_history": [
            {"role": "user", "content": "önceki tahliye sorusu"},
            {"role": "assistant", "content": f"{CLARIFY_MARKER} hangi sebeple?"},
            {"role": "user", "content": "ihtiyaç, kendim oturacağım sürekli"},
            {"role": "assistant", "content": "İhtiyaç nedeniyle tahliyede şu yol izlenir... [src:...]"},
        ],
    }
    assert decide_path(state) == "clarify"


def test_tenant_facing_eviction_not_treated_as_landlord():
    """Kiracı KENDİSİ tahliye ediliyorsa landlord-eviction değil → mevcut kalibrasyon
    (genel soru → answer) korunur; yanlış 'neden çıkarmak istiyorsun' sorusu sorulmaz."""
    state = {
        "response_intent": "legal_answer",
        "domain": "kira",
        "question": "ev sahibim beni tahliye etmek istiyor ne yapabilirim",
        "case_facts": {},
    }
    assert decide_path(state) == "answer"


def test_employer_dismissal_without_reason_clarifies():
    """İş hukuku fesih: işveren işçiyi çıkarmak istiyor ama SEBEP belli değil →
    sebep (haklı/geçerli/sebepsiz) kıdem-ihbar + işe iade hakkını belirler → sor."""
    state = {
        "response_intent": "legal_answer",
        "domain": "isHukuku",
        "question": "işçimi işten çıkarmak istiyorum ne yapmam gerekir",
        "case_facts": {"olay": "işçiyi işten çıkarmak istiyorum", "sure": "3 yıl"},
    }
    assert decide_path(state) == "clarify"


def test_employer_dismissal_reason_only_asks_followup():
    """Round-2: fesih sebebi (devamsızlık) verildi ama sebebe-özel belirleyici bilgi
    (tutanak/savunma/süre) yok → follow-up sor."""
    state = {
        "response_intent": "legal_answer",
        "domain": "isHukuku",
        "question": "devamsızlık yapan işçimi haklı sebeple çıkarmak istiyorum nasıl yaparım",
        "case_facts": {"olay": "devamsızlık nedeniyle işçi çıkarma"},
    }
    assert decide_path(state) == "clarify"


def test_employer_dismissal_full_picture_answers():
    """Fesih sebebi + sebebe-özel ayrıntı (tutanak/savunma) verildi → cevapla."""
    state = {
        "response_intent": "legal_answer",
        "domain": "isHukuku",
        "question": (
            "işçimi devamsızlıktan çıkardım; tutanak tuttum, yazılı savunmasını aldım, "
            "olayı 2 gün önce öğrendim"
        ),
        "case_facts": {"olay": "devamsızlık, tutanak ve savunma var"},
    }
    assert decide_path(state) == "answer"


def test_employee_dismissal_rights_question_still_answers():
    """Çalışanın KENDİ hak sorusu (işveren değil) → mevcut kalibrasyon korunur (answer);
    yanlış 'neden çıkarıyorsun' sorusu sorulmaz."""
    state = {
        "response_intent": "legal_answer",
        "domain": "isHukuku",
        "question": "işten haksız yere çıkarıldım hangi haklarım var",
        "case_facts": {},
    }
    assert decide_path(state) == "answer"


def test_non_discriminator_ishukuku_complaint_answers_with_facts():
    """Fesih DIŞI iş sorunu (ücret) + yeterli olgu → discriminator kapı kapalı, answer."""
    state = {
        "response_intent": "legal_answer",
        "domain": "isHukuku",
        "question": "fazla mesai ücretimi alamıyorum",
        "case_facts": {"olay": "fazla mesai ücreti ödenmiyor", "sure": "2 yıl"},
    }
    assert decide_path(state) == "answer"


def test_is_general_question_ability_pattern_typo_robust():
    """'...alabilir mi(yim)' yetenek sorusu = genel (cevapla); typo/birleşik dayanıklı.

    Prod-bug (2026-06-17): 'kdm tazminatı albilirmiyim' clarify'a düşüyordu — 'alabilir mi'
    marker'ı birleşik/typo formda eşleşmiyordu. Regex 'bil[ie]r mi' → typo'da bile yakalar.
    """
    from agents.policy import _is_general_question
    assert _is_general_question("kıdem tazminatı alabilir miyim")
    assert _is_general_question("kdm tazminatı albilirmiyim")       # typo + birleşik
    assert _is_general_question("işe iade davası açabilir miyim")
    assert _is_general_question("tazminatımı alabilirmiyim")
    # Durumsal şikâyet (yetenek sorusu DEĞİL) → genel değil → clarify korunur
    assert not _is_general_question("ev sahibim depozitomu vermiyor")
