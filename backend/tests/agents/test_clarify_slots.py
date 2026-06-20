"""clarify_slots — tahliye (discriminator) niyet tespiti + ayırt edici sorular."""

from __future__ import annotations

import re

from agents.clarify_slots import (
    discriminator_followup_questions,
    discriminator_options,
    discriminator_questions,
    dismissal_reason_present,
    eviction_reason_category,
    eviction_reason_present,
    fesih_clarify_questions,
    fesih_reason_category,
    icra_stance_category,
    is_discriminator_scenario,
    is_employer_dismissal,
    is_icra_situation,
    is_landlord_eviction,
    tahliye_clarify_questions,
)

# --- is_landlord_eviction: ev sahibi kiracısını çıkarmak istiyor ---

def test_detects_landlord_eviction():
    assert is_landlord_eviction("kiracımı çıkaramıyorum")
    assert is_landlord_eviction("kiracıyı çıkarmak istiyorum")
    assert is_landlord_eviction("kiracımı evden tahliye etmek istiyorum")
    assert is_landlord_eviction("kiracı kirayı ödemiyor, çıkarmak istiyorum")


def test_tenant_being_evicted_is_not_landlord_eviction():
    # Kullanıcı KENDİSİ tahliye edilen kiracı → sebep-sorma ağacı uygulanmamalı.
    assert not is_landlord_eviction("ev sahibim beni tahliye etmek istiyor")
    assert not is_landlord_eviction("kiracı olarak beni çıkarıyorlar")
    assert not is_landlord_eviction("evden çıkarıldım ne yapabilirim")


def test_non_eviction_kira_is_not_landlord_eviction():
    assert not is_landlord_eviction("kira artışı ne kadar olabilir")
    assert not is_landlord_eviction("ev sahibim depozitomu vermiyor")
    assert not is_landlord_eviction("kira sözleşmesi nasıl feshedilir")  # 'kiracı' yok


# --- eviction_reason_present ---

def test_reason_present_for_known_grounds():
    assert eviction_reason_present("kendi ihtiyacım için çıkarmak istiyorum")
    assert eviction_reason_present("kiracı kira borcunu ödemiyor")
    assert eviction_reason_present("kiracı tahliye taahhüdü vermişti")
    assert eviction_reason_present("binayı yeniden inşa edeceğim")


def test_reason_absent_for_bare_complaint():
    assert not eviction_reason_present("kiracımı çıkaramıyorum")
    assert not eviction_reason_present("kiracıyı çıkarmak istiyorum ne yapmalıyım")


# --- tahliye_clarify_questions ---

def test_asks_reason_first():
    questions = tahliye_clarify_questions({})
    assert 2 <= len(questions) <= 4
    assert "sebep" in questions[0].lower()  # ayırt edici: 'hangi sebeple'


def test_skips_known_reason_fact():
    # gerekce zaten biliniyorsa sebep sorusu atlanır (over-asking yok).
    questions = tahliye_clarify_questions({"gerekce": "ihtiyaç"})
    assert all("hangi sebeple" not in q.lower() for q in questions)
    assert len(questions) >= 2


def test_questions_have_no_legal_claims():
    # Sıfır halüsinasyon: sorular madde/karar numarası ya da kaynak-etiketi içermez.
    for q in tahliye_clarify_questions({}):
        assert not re.search(r"\bmadde\s*\d", q.lower())
        assert "[src:" not in q


# --- İş hukuku · fesih (işveren işçiyi çıkarıyor) ---

def test_detects_employer_dismissal():
    assert is_employer_dismissal("işçimi işten çıkarmak istiyorum")
    assert is_employer_dismissal("çalışanı işten çıkarmak istiyorum")
    assert is_employer_dismissal("işçinin iş akdini feshetmek istiyorum")


def test_employee_self_is_not_employer_dismissal():
    # Çalışanın KENDİSİ → işveren sebep-ağacı uygulanmaz (mevcut hak-akışı korunur).
    assert not is_employer_dismissal("işten haksız yere çıkarıldım hangi haklarım var")
    assert not is_employer_dismissal("kıdem tazminatı alabilir miyim")
    assert not is_employer_dismissal("patronum beni işten çıkardı ne yapabilirim")


def test_non_dismissal_ishukuku_is_not_employer_dismissal():
    assert not is_employer_dismissal("fazla mesai ücretimi alamıyorum")
    assert not is_employer_dismissal("kıdem tazminatı nasıl hesaplanır")


def test_dismissal_reason_markers():
    assert dismissal_reason_present("devamsızlık yapan işçiyi çıkaracağım")
    assert dismissal_reason_present("ekonomik nedenlerle küçülmeye gidiyoruz")
    assert not dismissal_reason_present("işçimi çıkarmak istiyorum")


def test_fesih_questions_ask_reason_first_no_legal_claims():
    questions = fesih_clarify_questions({})
    assert "sebep" in questions[0].lower()
    for q in questions:
        assert not re.search(r"\bmadde\s*\d", q.lower())


# --- genel dispatch ---

def test_dispatch_returns_questions_for_active_scenario():
    qs = discriminator_questions("kira", "kiracımı çıkaramıyorum", {"olay": "kiracıyı çıkaramıyorum"})
    assert qs and "sebep" in qs[0].lower()
    qs2 = discriminator_questions("isHukuku", "işçimi çıkarmak istiyorum", {})
    assert qs2 and "sebep" in qs2[0].lower()


def test_dispatch_none_when_reason_known_or_inactive():
    # sebep belli → round-1 None (round-2 follow-up'a bırakır)
    assert discriminator_questions("kira", "kendi ihtiyacım için kiracımı çıkaracağım", {}) is None
    # gerekce olgusu biliniyor → round-1 None
    assert discriminator_questions("kira", "kiracımı çıkaracağım", {"gerekce": "ihtiyaç"}) is None
    # senaryo aktif değil (domain'de discriminator yok) → None
    assert discriminator_questions("tuketici", "ayıplı ürün aldım çıkar", {}) is None
    # kira ama tahliye değil → None
    assert discriminator_questions("kira", "depozitomu alamıyorum", {}) is None


# --- round-2 dallanma: sebebe-özel follow-up ---

def test_eviction_reason_category_classifies():
    assert eviction_reason_category("kendi ihtiyacım için") == "ihtiyac"
    assert eviction_reason_category("kira borcunu ödemiyor") == "temerrut"
    assert eviction_reason_category("yazılı tahliye taahhüdü var") == "taahhut"
    assert eviction_reason_category("binayı yeniden inşa edeceğim") == "insa"
    assert eviction_reason_category("10 yıldır oturuyor") == "on_yil"
    assert eviction_reason_category("evi yeni satın aldım") == "yeni_malik"
    assert eviction_reason_category("kiracımı çıkaramıyorum") is None  # sebep yok


def test_followup_asks_reason_specific_when_reason_present():
    # ihtiyaç sebebi belli, sebebe-özel ayrıntı yok → 'kim oturacak/sürekli mi' sor.
    qs = discriminator_followup_questions(
        "kira", "kendi ihtiyacım için çıkarmak istiyorum",
        {"olay": "kiracıyı ihtiyaç nedeniyle çıkarmak istiyorum"},
    )
    assert qs and ("oturac" in qs[0].lower() or "sürekli" in qs[0].lower())


def test_followup_none_when_reason_absent():
    # Sebep henüz belli değil → bu round-1 işi, follow-up değil.
    assert discriminator_followup_questions("kira", "kiracımı çıkaramıyorum", {}) is None


def test_followup_none_when_specifics_already_given():
    # Sebebe-özel bilgi zaten verilmiş → over-asking yok.
    qs = discriminator_followup_questions(
        "kira", "kendi ihtiyacım için, eşimle biz oturacağız sürekli", {},
    )
    assert qs is None


def test_followup_none_for_domain_without_scenario():
    # Discriminator senaryosu olmayan domain (tüketici) → follow-up yok.
    assert discriminator_followup_questions("tuketici", "ayıplı ürün aldım iade istiyorum", {}) is None


def test_fesih_followup_asks_reason_specific_when_reason_present():
    # İş-fesih round-2: devamsızlık (haklı sebep) belli, ayrıntı yok → tutanak/savunma sor.
    qs = discriminator_followup_questions(
        "isHukuku", "işçimi devamsızlıktan çıkaracağım",
        {"olay": "devamsızlık nedeniyle işçi çıkarma"},
    )
    assert qs and ("tutanak" in qs[0].lower() or "savunma" in qs[0].lower())


def test_fesih_followup_none_when_specifics_given():
    qs = discriminator_followup_questions(
        "isHukuku", "işçimi devamsızlıktan çıkardım, tutanak ve savunma aldım", {},
    )
    assert qs is None


def test_fesih_reason_category_classifies():
    from agents.clarify_slots import fesih_reason_category
    assert fesih_reason_category("devamsızlık yaptı") == "hakli_isci"
    assert fesih_reason_category("performans düşüklüğü") == "gecerli"
    assert fesih_reason_category("ekonomik küçülme") == "ekonomik"
    assert fesih_reason_category("işçimi çıkaracağım") is None


def test_is_discriminator_scenario_detects_active_domains():
    assert is_discriminator_scenario("kira", "kiracımı çıkaramıyorum", {})
    assert is_discriminator_scenario("isHukuku", "işçimi işten çıkaracağım", {})
    assert not is_discriminator_scenario("kira", "depozitomu alamıyorum", {})
    assert not is_discriminator_scenario("tuketici", "ayıplı ürün", {})


# --- tıklanabilir sebep-şıkları (round-1 cevap-chip) ---

def test_eviction_options_returned_in_round1():
    opts = discriminator_options("kira", "kiracımı çıkaramıyorum", {})
    assert opts and len(opts) == 6


def test_each_eviction_option_maps_to_category_and_triggers_followup():
    # Her şık bir sebep TAŞIR (kategori eşlesin) ve gerçek akışta (şık + birikmiş olay)
    # tıklanınca sebebe-özel round-2 follow-up tetiklenir.
    opts = discriminator_options("kira", "kiracımı çıkaramıyorum", {})
    for opt in opts:
        assert eviction_reason_category(opt) is not None, opt
        followup = discriminator_followup_questions(
            "kira", opt, {"olay": "kiracıyı çıkaramıyorum"},
        )
        assert followup is not None, opt


def test_fesih_options_map_to_category_and_trigger_followup():
    opts = discriminator_options("isHukuku", "işçimi çıkaracağım", {})
    assert opts and len(opts) == 3
    for opt in opts:
        assert fesih_reason_category(opt) is not None, opt
        followup = discriminator_followup_questions(
            "isHukuku", opt, {"olay": "işçiyi çıkaracağım"},
        )
        assert followup is not None, opt


def test_options_none_in_round2_or_inactive():
    # sebep belli (round-2) → şık yok
    assert discriminator_options("kira", "kendi ihtiyacım için çıkaracağım", {}) is None
    # senaryo pasif (tahliye değil / domain yok)
    assert discriminator_options("kira", "depozitomu alamıyorum", {}) is None
    assert discriminator_options("tuketici", "ayıplı ürün aldım", {}) is None


def test_options_have_no_legal_claims():
    for opt in discriminator_options("kira", "kiracımı çıkaramıyorum", {}):
        assert not re.search(r"\bmadde\s*\d", opt.lower())
        assert "[src:" not in opt


# --- serbest-metin (chip yerine kendi cümlesiyle yazma) sağlamlığı ---

def test_natural_freetext_reasons_recognized():
    # Kullanıcı şıkka tıklamak yerine kendi doğal ifadesiyle yazarsa da sebep tanınır.
    cases = {
        "kira vermiyor": "temerrut",
        "kirayı yatırmıyor": "temerrut",
        "kira ödenmiyor": "temerrut",
        "kendim oturmak istiyorum": "ihtiyac",
        "oğluma lazım oturacak": "ihtiyac",
        "dükkan açacağım": "ihtiyac",
        "binayı yeniden yapacağım": "insa",
    }
    for text, cat in cases.items():
        assert eviction_reason_category(text) == cat, text
        assert eviction_reason_present(text), text


def test_freetext_reason_triggers_round2_followup():
    # Serbest-metin sebep + birikmiş olay → round-2 sebebe-özel soru tetiklenir (chip gibi).
    for txt in ["kira vermiyor", "kendim oturmak istiyorum", "dükkan açacağım"]:
        fu = discriminator_followup_questions("kira", txt, {"olay": "kiracıyı çıkaramıyorum"})
        assert fu is not None, txt


def test_natural_freetext_dismissal_reasons_recognized():
    # İş-fesih: kullanıcı sebebi kendi cümlesiyle yazarsa da tanınır (tek-kaynak DRY).
    cases = {
        "işe gelmiyor": "hakli_isci",
        "sürekli geç geliyor": "hakli_isci",
        "verimsiz çalışıyor": "gecerli",
        "iş yapamıyor": "gecerli",
        "iş yok artık": "ekonomik",
        "zarar ediyoruz": "ekonomik",
    }
    for text, cat in cases.items():
        assert fesih_reason_category(text) == cat, text
        assert dismissal_reason_present(text), text


def test_dismissal_extra_reasons_present_without_category():
    # deneme süresi/emeklilik → sebep belli sayılır (present) ama round-2 kategorisi yok.
    assert dismissal_reason_present("deneme süresinde çıkaracağım")
    assert dismissal_reason_present("emeklilik nedeniyle ayrılıyor")
    assert fesih_reason_category("deneme süresinde çıkaracağım") is None


def test_freetext_dismissal_reason_triggers_followup():
    for txt in ["işe gelmiyor", "verimsiz çalışıyor", "iş yok artık"]:
        fu = discriminator_followup_questions("isHukuku", txt, {"olay": "işçiyi çıkaracağım"})
        assert fu is not None, txt


# --- icra: karşılaşılan icra olayında duruş (stance) discriminator'ı ---

def test_icra_situation_requires_event_not_general_howto():
    assert is_icra_situation("hakkımda icra takibi başlatıldı")
    assert is_icra_situation("ödeme emri geldi ne yapmalıyım")
    assert is_icra_situation("maaşıma haciz geldi")
    # Genel/tanımsal (karşılaşılan olay yok) → tetiklenmez (answer kalır)
    assert not is_icra_situation("icra takibi nasıl açılır")
    assert not is_icra_situation("haciz nasıl kaldırılır")
    assert not is_icra_situation("ödeme emrine itiraz nasıl yapılır")


def test_icra_stance_category_classifies():
    assert icra_stance_category("borca itiraz edeceğim") == "itiraz"
    assert icra_stance_category("borcu kabul etmiyorum") == "itiraz"
    assert icra_stance_category("borcu kabul ediyorum taksit istiyorum") == "kabul"
    assert icra_stance_category("alacaklıyım takip başlatacağım") == "alacakli"
    assert icra_stance_category("ödeme emri geldi") is None  # duruş henüz yok


def test_icra_options_map_to_stance_and_trigger_followup():
    opts = discriminator_options("icra", "ödeme emri geldi", {})
    assert opts and len(opts) == 3
    for opt in opts:
        assert icra_stance_category(opt) is not None, opt
        fu = discriminator_followup_questions(
            "icra", opt, {"olay": "hakkımda icra takibi başlatıldı"},
        )
        assert fu is not None, opt


def test_icra_no_discriminator_for_general_howto():
    assert discriminator_options("icra", "icra takibi nasıl açılır", {}) is None
    assert discriminator_questions("icra", "icra takibi nasıl açılır", {}) is None
