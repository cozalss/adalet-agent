"""Ayırt edici (discriminator) netleştirme şemaları — CLAM 'generate' aşaması.

Bazı sorularda doğru cevap, BİRKAÇ ayırt edici parametreye göre TAMAMEN değişir:
- Konut kirası TAHLİYE → ev sahibinin kiracıyı hangi SEBEPLE çıkardığı (ihtiyaç /
  kira ödememe / yazılı tahliye taahhüdü / yeniden inşa / 10 yıllık uzama / yeni malik)
  izlenecek yolu, süreleri ve dava türünü değiştirir.
- İş hukuku FESİH → işverenin işçiyi hangi SEBEPLE çıkardığı (haklı / geçerli /
  sebepsiz; işçiden mi işletmeden mi kaynaklı) kıdem-ihbar tazminatı ile işe iade
  hakkını tümden değiştirir.
Bu modül, o ayırt edici parametre eksikse SORULACAK olgu-toplayıcı soruları tanımlar.

Tasarım dayanağı (deep-research, doğrulanmış): CLAM 3-aşamalı seçici netleştirme
(arXiv 2212.07769 / 2311.09469) — *belirsizliği tespit et → doğru netleştirici soruyu
üret → cevapla*; ve A2J Author/Amazon: yalnız kullanıcının yolundaki ayırt edici soruyu
sor (aşırı-soru zararlı). Bu modül o 'üret' aşamasını VERİ-ODAKLI yapar: domain başına
bir senaryo (detect/reason/questions) kayıt-tablosunda; yeni alan = bir satır.

Sorular vatandaş dilindedir ve madde/karar/kanun numarası İÇERMEZ — hukuki iddiayı
draft/mevzuat üretir (sıfır halüsinasyon yüzeyi). Sebep adları (ihtiyaç, devamsızlık...)
hukuki İDDİA değil; kullanıcının durumunu sınıflamak için sunulan ŞIKLARDIR. Niyet
tespiti tr-lowercase substring ile deterministiktir (LLM yok); policy ile clarifier
AYNI `discriminator_questions()` yardımcısını kullanır (DRY — tek doğru kaynak).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from core.text import tr_lower as _tr_lower

# Slot tanımı: (fact_key | None, soru). fact_key verilmiş + o olgu biliniyorsa
# soru ATLANIR (over-asking'i önle). fact_key=None → her zaman sorulur.
_Slots = tuple[tuple[str | None, str], ...]


def _select_from_slots(slots: _Slots, case_facts: dict[str, object] | None) -> list[str]:
    """Slot listesinden, bilinen olguların sorusunu atlayarak soruları döndür."""
    known = {key for key, val in (case_facts or {}).items() if str(val).strip()}
    questions = [q for fact_key, q in slots if fact_key is None or fact_key not in known]
    if not questions:  # tümü atlandıysa (beklenmez) en azından ilk (en ayırt edici) soruyu sor
        questions = [slots[0][1]]
    return questions


# ───────────────────────── KİRA · TAHLİYE ─────────────────────────

_EVICTION_VERBS: tuple[str, ...] = ("çıkar", "tahliye", "boşalt")

# Kullanıcının KENDİSİ tahliye edilen kiracı olduğunu gösteren işaretler → sebep-sorma
# ağacı UYGULANMAZ (yanlış soru sormamak için).
_TENANT_SELF_MARKERS: tuple[str, ...] = (
    "ev sahib", "beni çıkar", "beni tahliye", "çıkarıldım", "çıkarılıyor",
    "tahliye davası açtı", "bana tahliye", "bizi çıkar",
)

def is_landlord_eviction(text: str) -> bool:
    """Metin 'ev sahibi kiracısını çıkarmak istiyor' senaryosu mu? (dar kapsam)."""
    low = _tr_lower(text or "")
    if "kiracı" not in low:
        return False
    if any(marker in low for marker in _TENANT_SELF_MARKERS):
        return False
    return any(verb in low for verb in _EVICTION_VERBS)


def eviction_reason_present(text: str) -> bool:
    """Tahliye sebebi metinde belirtilmiş mi? TEK KAYNAK: `_EVICTION_REASON_GROUPS`
    (kategori eşleşmesi). Böylece chip ile SERBEST-METİN aynı tanımayı kullanır (DRY) —
    kullanıcı sebebi kendi cümleleriyle yazsa da chip'e tıklasa da aynı round-2 tetiklenir."""
    return eviction_reason_category(text) is not None


_TAHLIYE_SLOTS: _Slots = (
    (
        "gerekce",
        "Kiracıyı hangi sebeple çıkarmak istiyorsunuz? Örneğin: kendinizin veya "
        "yakınınızın konut/işyeri ihtiyacı, kira bedelinin ödenmemesi, kiracının "
        "verdiği yazılı tahliye taahhüdü, binayı yeniden inşa/esaslı onarım, "
        "10 yıldan uzun süredir oturuyor olması ya da taşınmazı yeni satın almış "
        "olmanız.",
    ),
    (
        None,
        "Kira sözleşmeniz yazılı mı ve süresi ne kadar? (örneğin 1 yıllık; varsa "
        "başlangıç tarihiyle birlikte belirtin.)",
    ),
    (
        None,
        "Kiracıya bu konuda yazılı bir ihtar/bildirim (ihtarname) gönderdiniz mi? "
        "Gönderdiyseniz yaklaşık ne zaman?",
    ),
)


def tahliye_clarify_questions(case_facts: dict[str, object] | None) -> list[str]:
    """Tahliye için ayırt edici soruları, bilinen olguları atlayarak döndür."""
    return _select_from_slots(_TAHLIYE_SLOTS, case_facts)


# Round-2 dallanma: kullanıcı sebebi belirttikten SONRA, sebebe-özel belirleyici
# soruyu sor. Her grup: kategori → (tanıma-işaretleri, takip-sorusu, zaten-cevaplı-işaretleri).
# zaten-cevaplı işaretler metinde varsa follow-up SORULMAZ (over-asking yok).
# Sebep tanıma — TEK KAYNAK (hem eviction_reason_present hem eviction_reason_category).
# Chip etiketleri + DOĞAL serbest-metin ("kira vermiyor", "kendim oturacağım",
# "dükkan açacağım"...) yakalanacak şekilde geniş tutulur; her marker bir round-2
# kategorisine eşler. (Vatandaş dili; madde no YOK.)
_EVICTION_REASON_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ihtiyac", ("ihtiyac", "ihtiyaç", "oturac", "oturmak", "kendim", "kendi ih",
                 "işyeri açac", "iş yeri açac", "dükkan açac", "yakınım",
                 "annem", "babam", "oğlum", "kızım", "eşim")),
    ("temerrut", ("ödemiyor", "ödemedi", "ödememe", "ödenmiyor", "ödenmedi",
                  "kira vermiyor", "kirayı vermiyor", "kira gelmiyor", "yatırm",
                  "kira borcu", "borcunu", "temerrüt", "geç ödü", "geç yatır",
                  "iki haklı ihtar")),
    ("taahhut", ("taahhü",)),
    ("insa", ("yeniden inşa", "yeniden yap", "yıkıp", "tadilat", "esaslı tamir",
              "esaslı onar", "imar")),
    ("on_yil", ("10 yıl", "on yıl", "uzayan", "uzama süresi")),
    ("yeni_malik", ("yeni aldım", "yeni satın", "satın aldım", "yeni malik")),
)

# kategori → (sebebe-özel takip sorusu, zaten-cevaplı kök-işaretler).
_EVICTION_FOLLOWUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "ihtiyac": (
        "Konutta/işyerinde kim oturacak veya kullanacak — kendiniz, eşiniz, "
        "altsoyunuz/üstsoyunuz ya da bakmakla yükümlü olduğunuz biri mi? Bu ihtiyaç "
        "gerçek ve sürekli mi?",
        ("oturac", "sürekli", "gerçek ihtiyac", "kullanac"),
    ),
    "temerrut": (
        "Kira borcu için kiracıya yazılı ihtar ya da ödeme emri gönderdiniz mi? Bir "
        "kira yılı içinde kaç kez geç ödeme veya ihtar oldu?",
        ("ihtar gönder", "ihtarname", "ödeme emri", "iki kez", "iki haklı ihtar"),
    ),
    "taahhut": (
        "Tahliye taahhüdü yazılı mı ve kira sözleşmesi yapıldıktan sonraki bir tarihte "
        "mi verildi? Taahhütte belirtilen tahliye tarihi neydi?",
        ("noterden", "yazılı taahhüt", "sözleşmeden sonra", "taahhüt tarih"),
    ),
    "insa": (
        "Yapılacak inşaat/onarım kiracının oturmasına engel olacak kapsamlı (esaslı) "
        "bir tadilat mı? Onaylı bir projeniz veya ruhsatınız var mı?",
        ("ruhsat", "onaylı proje", "esaslı tadilat", "oturulamaz"),
    ),
    "on_yil": (
        "Sözleşme kaç yıldır devam ediyor ve uzama süresi dahil 10 yılı doldurdu mu? "
        "Fesih bildirimini ne zaman yapmayı planlıyorsunuz?",
        ("doldur", "bildirim yapt", "fesih ihbar"),
    ),
    "yeni_malik": (
        "Taşınmazı ne zaman satın aldınız ve kiracıya yeni malik olduğunuzu yazılı "
        "olarak bildirdiniz mi?",
        ("yazılı bildir", "tapu tarih", "ihtar gönder"),
    ),
}


def eviction_reason_category(text: str) -> str | None:
    """Tahliye sebebi hangi TBK yoluna işaret ediyor? (ilk eşleşen kategori)."""
    low = _tr_lower(text or "")
    for category, markers in _EVICTION_REASON_GROUPS:
        if any(marker in low for marker in markers):
            return category
    return None


# Round-1 cevap-ŞIKLARI (tıklanabilir chip): kullanıcı sebebi yazmak yerine seçer.
# Her etiket bir sebep-anahtarı İÇERİR (eviction_reason_category eşlesin) ama round-2
# "zaten-cevaplı" işaretlerini İÇERMEZ (tıklayınca sebebe-özel follow-up yine sorulsun).
_EVICTION_OPTIONS: tuple[str, ...] = (
    "İhtiyaç nedeniyle (kendi/yakın konut-işyeri)",
    "Kira bedeli ödenmiyor (temerrüt)",
    "Tahliye taahhüdü vermişti",
    "Binayı yeniden inşa / esaslı onarım",
    "10 yıldan uzun süredir oturuyor",
    "Taşınmazı yeni satın aldım",
)


def _tahliye_followup(text: str, case_facts: dict[str, object] | None) -> list[str] | None:
    """Sebep belliyse sebebe-özel takip sorusunu döndür; bilgi zaten varsa None."""
    category = eviction_reason_category(text)
    if category is None:
        return None
    question, answered_markers = _EVICTION_FOLLOWUPS[category]
    low = _tr_lower(f"{text} {(case_facts or {}).get('olay', '')}")
    if any(marker in low for marker in answered_markers):
        return None  # sebebe-özel bilgi zaten verilmiş → round-2 gereksiz
    return [question]


# ───────────────────────── İŞ HUKUKU · FESİH ─────────────────────────

# Kök formlar — tüm çekimleri yakalar ("çıkar" → çıkarmak/çıkardım/çıkaracağım/
# çıkarıyorum; "fesh" → feshetmek/feshettim/iş akdini feshet). "işçi/çalışan"
# zorunluluğu + işçi-self guard yanlış-pozitifi düşük tutar.
_DISMISSAL_VERBS: tuple[str, ...] = (
    "çıkar", "işten at", "işine son", "kov", "fesh", "akdini sonland", "tazminatsız",
)

# Kullanıcının KENDİSİ çıkarılan/çıkan işçi olduğu işaretler → işveren sebep-ağacı UYGULANMAZ.
_EMPLOYEE_SELF_MARKERS: tuple[str, ...] = (
    "çıkarıldım", "çıkartıldım", "kovuldum", "işten atıldım", "işten çıktım",
    "beni çıkar", "beni işten", "işveren beni", "patronum beni", "istifa ettim",
    "haklarım", "kıdem alabilir", "kıdem alır", "tazminat alabilir", "işe iade",
)

# Round-2 kategorisi OLMAYAN ama yine de geçerli fesih sebepleri: tanınır (sebep belli
# sayılır → tekrar sorulmaz) ama sebebe-özel follow-up yok (bu yollar daha düz).
_DISMISSAL_EXTRA_REASONS: tuple[str, ...] = ("deneme süresi", "emeklilik")


def is_employer_dismissal(text: str) -> bool:
    """Metin 'işveren işçisini işten çıkarmak istiyor' senaryosu mu? (dar kapsam).

    'işçi' (veya çalışan/personel/eleman) geçmeli + bir fesih fiili olmalı +
    kullanıcının kendisi çıkarılan işçi OLMAMALI (çalışan hak-sorusu mevcut akışta
    kalsın, yanlış 'neden çıkarıyorsun' sorusu sorulmasın).
    """
    low = _tr_lower(text or "")
    if not any(ref in low for ref in ("işçi", "çalışan", "personel", "eleman")):
        return False
    if any(marker in low for marker in _EMPLOYEE_SELF_MARKERS):
        return False
    return any(verb in low for verb in _DISMISSAL_VERBS)


def dismissal_reason_present(text: str) -> bool:
    """Fesih sebebi metinde belirtilmiş mi? TEK KAYNAK: `_DISMISSAL_REASON_GROUPS`
    (kategori eşleşmesi) + kategorisiz-ama-geçerli sebepler (deneme süresi/emeklilik).
    Chip ile serbest-metin aynı tanımayı kullanır (DRY)."""
    if fesih_reason_category(text) is not None:
        return True
    low = _tr_lower(text or "")
    return any(reason in low for reason in _DISMISSAL_EXTRA_REASONS)


_FESIH_SLOTS: _Slots = (
    (
        "gerekce",
        "İşçiyi hangi sebeple çıkarmak istiyorsunuz? Örneğin: devamsızlık, "
        "performans/verim düşüklüğü, disiplinsizlik veya güveni kötüye kullanma gibi "
        "işçiden kaynaklanan bir sebep; ekonomik/işletmesel küçülme; ya da belirli "
        "bir sebep olmaksızın.",
    ),
    ("sure", "İşçi bu işyerinde ne kadar süredir çalışıyor?"),
    ("isci_sayisi", "İşyerinde yaklaşık kaç kişi çalışıyor?"),
)


def fesih_clarify_questions(case_facts: dict[str, object] | None) -> list[str]:
    """İş feshinde ayırt edici soruları, bilinen olguları atlayarak döndür."""
    return _select_from_slots(_FESIH_SLOTS, case_facts)


# Round-2 dallanma: fesih sebebi belliyse sebebe-özel belirleyici soru.
# Sebep tanıma — TEK KAYNAK (fesih_reason_category + dismissal_reason_present).
# Chip + DOĞAL serbest-metin ("işe gelmiyor", "verimsiz", "iş yok artık"...) yakalanır.
_DISMISSAL_REASON_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hakli_isci", ("haklı sebep", "haklı neden", "devamsızlık", "işe gelm",
                    "geç geliyor", "izinsiz", "disiplin", "kurallara uym", "hırsızlık",
                    "güveni kötüye", "kavga", "hakaret", "saygısız")),
    ("gecerli", ("geçerli sebep", "geçerli neden", "performans", "verim düşük",
                 "verimsiz", "yetersiz", "iş yapamıyor", "beceriksiz")),
    ("ekonomik", ("ekonomik", "küçülme", "işletmesel", "iş azal", "iş yok",
                  "kapanıyor", "zarar ed", "tasarruf", "personel azalt")),
)

_DISMISSAL_FOLLOWUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "hakli_isci": (
        "Bu davranışı tutanak ve işçinin yazılı savunmasıyla belgelediniz mi? Olayı "
        "öğrendiğinizden bu yana kaç gün geçti?",
        ("tutanak", "savunma", "belgeled", "gün geç", "gün önce"),
    ),
    "gecerli": (
        "İşçiye yazılı savunma hakkı verdiniz mi ve yetersizlik/performans durumunu "
        "yazılı uyarı ya da değerlendirmeyle belgelediniz mi?",
        ("savunma", "yazılı uyar", "belgeled", "değerlendir"),
    ),
    "ekonomik": (
        "Fesih son çare miydi; işçiye başka bir pozisyon ya da çözüm sundunuz mu? "
        "İşyerinde 30 veya daha fazla işçi var mı ve bu işçi 6 aydan uzun süredir mi çalışıyor?",
        ("son çare", "başka pozisyon", "30 işçi", "otuz işçi", "altı ay", "6 ay"),
    ),
}


def fesih_reason_category(text: str) -> str | None:
    """Fesih sebebi hangi türe işaret ediyor? (işçiden haklı / geçerli / ekonomik)."""
    low = _tr_lower(text or "")
    for category, markers in _DISMISSAL_REASON_GROUPS:
        if any(marker in low for marker in markers):
            return category
    return None


# Round-1 cevap-şıkları (tıklanabilir chip) — fesih sebebi seçimi.
_FESIH_OPTIONS: tuple[str, ...] = (
    "Devamsızlık / disiplinsizlik (işçiden haklı sebep)",
    "Performans / yetersizlik",
    "Ekonomik / işletmesel küçülme",
)


def _fesih_followup(text: str, case_facts: dict[str, object] | None) -> list[str] | None:
    """Fesih sebebi belliyse sebebe-özel takip sorusu; bilgi zaten varsa None."""
    category = fesih_reason_category(text)
    if category is None:
        return None
    question, answered_markers = _DISMISSAL_FOLLOWUPS[category]
    low = _tr_lower(f"{text} {(case_facts or {}).get('olay', '')}")
    if any(marker in low for marker in answered_markers):
        return None
    return [question]


# ───────────────────────── İCRA · TAKİP DURUMU ─────────────────────────
#
# İcra'da "ne yapmalı" cevabı, kullanıcının DURUŞUNA (stance) göre tümden değişir:
# borca/takibe itiraz mı, borcu kabul edip ödeme/taksit mi, yoksa kullanıcı alacaklı
# olarak takip mi başlatacak. Bu yüzden stance = ayırt edici parametre.
#
# SIKI tespit (genel "icra takibi nasıl açılır" sorularıyla çakışmamak için): yalnız
# KARŞILAŞILAN bir icra OLAYI varsa (ödeme emri geldi / haciz / tebliğ) tetiklenir.
_ICRA_TOPIC_MARKERS: tuple[str, ...] = ("ödeme emri", "icra", "haciz", "takip")
_ICRA_EVENT_MARKERS: tuple[str, ...] = (
    "geldi", "aldım", "başlatıl", "başlattı", "başladı", "tebliğ", "haczedil",
    "hakkımda", "açıldı", "gönderdi", "kesildi", "el konuldu", "maaşıma",
)


def is_icra_situation(text: str) -> bool:
    """Kullanıcı KARŞILAŞTIĞI bir icra olayını mı anlatıyor? (genel how-to DEĞİL).

    İcra konusu + bir 'karşılaşma' olayı (geldi/haciz/tebliğ...) gerekir; böylece
    'icra takibi nasıl açılır' gibi tanımsal sorular tetiklenmez (answer kalır)."""
    low = _tr_lower(text or "")
    if not any(topic in low for topic in _ICRA_TOPIC_MARKERS):
        return False
    return any(event in low for event in _ICRA_EVENT_MARKERS)


_ICRA_STANCE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # itiraz ÖNCE (borcu kabul ETMİYORUM, kabul'den ayrışsın)
    ("itiraz", ("itiraz", "borç bana ait değil", "borcu kabul etmiyorum", "borcum yok",
                "haksız", "ödedim zaten", "tanımıyorum", "borca itiraz", "imzaya itiraz")),
    ("kabul", ("kabul ediyorum", "borcu kabul", "borcum var", "taksit", "ödemek istiyorum",
               "ödeyeceğim", "yapılandır")),
    ("alacakli", ("alacaklıyım", "alacağımı", "takip başlat", "tahsil et",
                  "senedim var", "çekim var", "param var")),
)


def icra_stance_category(text: str) -> str | None:
    """Kullanıcının icra duruşu (itiraz / kabul / alacaklı)."""
    low = _tr_lower(text or "")
    for category, markers in _ICRA_STANCE_GROUPS:
        if any(marker in low for marker in markers):
            return category
    return None


def icra_stance_present(text: str) -> bool:
    """İcra duruşu belli mi? TEK KAYNAK: `_ICRA_STANCE_GROUPS` (chip+serbest-metin DRY)."""
    return icra_stance_category(text) is not None


_ICRA_SLOTS: _Slots = (
    (
        "gerekce",
        "İcra sürecinde durumunuz ne? Borca/takibe itiraz mı edeceksiniz, borcu kabul "
        "edip ödeme/taksit mi istiyorsunuz, yoksa siz mi alacaklı olarak takip "
        "başlatacaksınız?",
    ),
    (None, "Size ödeme emri veya tebligat ulaştı mı? Yaklaşık ne zaman?"),
)


def icra_clarify_questions(case_facts: dict[str, object] | None) -> list[str]:
    """İcra'da ayırt edici (stance) soruları, bilinen olguları atlayarak döndür."""
    return _select_from_slots(_ICRA_SLOTS, case_facts)


_ICRA_OPTIONS: tuple[str, ...] = (
    "Borca/takibe itiraz edeceğim",
    "Borcu kabul ediyorum, ödemek istiyorum",
    "Alacaklıyım, takip başlatacağım",
)

_ICRA_FOLLOWUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "itiraz": (
        "Size ödeme emri tebliğ edileli kaç gün oldu? İtirazınız borcun tamamına mı, "
        "yoksa imzaya/faize mi yönelik?",
        ("gün oldu", "gün önce", "imzaya", "faize", "tamamına"),
    ),
    "kabul": (
        "Borcu tek seferde mi ödeyeceksiniz yoksa taksit/yapılandırma mı istiyorsunuz? "
        "Maaş veya mal haczi başladı mı?",
        ("taksit", "tek sefer", "haciz başla", "maaş haczi"),
    ),
    "alacakli": (
        "Elinizde senet, çek veya sözleşme gibi bir belge var mı? Borçlunun güncel "
        "adres/iletişim bilgisi elinizde mi?",
        ("senet", "çek", "sözleşme", "adres"),
    ),
}


def _icra_followup(text: str, case_facts: dict[str, object] | None) -> list[str] | None:
    """İcra duruşu belliyse duruşa-özel takip sorusu; bilgi zaten varsa None."""
    category = icra_stance_category(text)
    if category is None:
        return None
    question, answered_markers = _ICRA_FOLLOWUPS[category]
    low = _tr_lower(f"{text} {(case_facts or {}).get('olay', '')}")
    if any(marker in low for marker in answered_markers):
        return None
    return [question]


# ───────────────────────── GENEL DİSPATCH ─────────────────────────


@dataclass(frozen=True)
class _Scenario:
    """Bir domain için ayırt edici netleştirme senaryosu (CLAM 'generate' veri-odaklı).

    detect: bu senaryo aktif mi? (ör. ev-sahibi-tahliye / işveren-fesih)
    reason_present: ayırt edici SEBEP metinde belli mi?
    reason_fact_key: bu olgu biliniyorsa sebep biliniyor sayılır (round-1 atlanır)
    questions: round-1 (sebep) soruları
    followup: round-2 sebebe-özel takip soruları (yoksa None → tek tur)
    """

    detect: Callable[[str], bool]
    reason_present: Callable[[str], bool]
    reason_fact_key: str
    questions: Callable[[dict[str, object] | None], list[str]]
    followup: Callable[[str, dict[str, object] | None], list[str] | None] | None = None
    options: tuple[str, ...] = ()  # round-1 tıklanabilir cevap-şıkları (sebep seçimi)


# domain → senaryo. Yeni ayırt edici alan eklemek = buraya bir satır + saf fonksiyonlar.
_SCENARIOS: dict[str, _Scenario] = {
    "kira": _Scenario(
        is_landlord_eviction, eviction_reason_present, "gerekce",
        tahliye_clarify_questions, _tahliye_followup, _EVICTION_OPTIONS,
    ),
    "isHukuku": _Scenario(
        is_employer_dismissal, dismissal_reason_present, "gerekce",
        fesih_clarify_questions, _fesih_followup, _FESIH_OPTIONS,
    ),
    "icra": _Scenario(
        is_icra_situation, icra_stance_present, "gerekce",
        icra_clarify_questions, _icra_followup, _ICRA_OPTIONS,
    ),
}


def _scenario_text(question: str, facts: dict[str, object]) -> str:
    """Tespit/sebep metni: soru + birikmiş olay + (varsa) gerekce olgusu."""
    return f"{question or ''} {facts.get('olay', '')} {facts.get('gerekce', '')}"


def is_discriminator_scenario(
    domain: str, question: str, case_facts: dict[str, object] | None
) -> bool:
    """Bu domain/metin bir ayırt edici senaryo mu? (sebep verildiyse cevap için yeterli)."""
    sc = _SCENARIOS.get(domain)
    if sc is None:
        return False
    return sc.detect(_scenario_text(question, case_facts or {}))


def discriminator_questions(
    domain: str, question: str, case_facts: dict[str, object] | None
) -> list[str] | None:
    """ROUND-1: sebep eksikse SORULACAK soruları döndür; sebep belli/senaryo pasifse None."""
    sc = _SCENARIOS.get(domain)
    if sc is None:
        return None
    facts = case_facts or {}
    if str(facts.get(sc.reason_fact_key, "")).strip():
        return None  # sebep olgu olarak zaten biliniyor → round-1 yok
    text = f"{question or ''} {facts.get('olay', '')}"
    if not sc.detect(text):
        return None
    if sc.reason_present(text):
        return None  # sebep metinde belli → round-1 yok (round-2'ye bırak)
    return sc.questions(facts)


def discriminator_followup_questions(
    domain: str, question: str, case_facts: dict[str, object] | None
) -> list[str] | None:
    """ROUND-2: sebep belliyse sebebe-özel takip sorusu; sebep yok/zaten cevaplıysa None."""
    sc = _SCENARIOS.get(domain)
    if sc is None or sc.followup is None:
        return None
    facts = case_facts or {}
    text = _scenario_text(question, facts)
    if not sc.detect(text):
        return None
    if not sc.reason_present(text):
        return None  # sebep henüz belli değil → bu round-1 işi, follow-up değil
    return sc.followup(text, facts)


def discriminator_options(
    domain: str, question: str, case_facts: dict[str, object] | None
) -> list[str] | None:
    """ROUND-1 tıklanabilir cevap-şıkları (sebep seçimi); round-1 değilse None.

    Şartlar round-1 sebep-sorusuyla AYNI (sebep henüz belli değil). Şıklar CEVAP'tır
    (soru değil) — tıklayınca o sebep kullanıcı yanıtı olarak gider, round-2'yi tetikler.
    """
    sc = _SCENARIOS.get(domain)
    if sc is None or not sc.options:
        return None
    facts = case_facts or {}
    if str(facts.get(sc.reason_fact_key, "")).strip():
        return None
    text = f"{question or ''} {facts.get('olay', '')}"
    if not sc.detect(text):
        return None
    if sc.reason_present(text):
        return None
    return list(sc.options)


__all__ = (
    "discriminator_followup_questions",
    "discriminator_options",
    "discriminator_questions",
    "dismissal_reason_present",
    "eviction_reason_category",
    "eviction_reason_present",
    "fesih_clarify_questions",
    "fesih_reason_category",
    "icra_clarify_questions",
    "icra_stance_category",
    "icra_stance_present",
    "is_discriminator_scenario",
    "is_employer_dismissal",
    "is_icra_situation",
    "is_landlord_eviction",
    "tahliye_clarify_questions",
)
