"""İçerik-risk veto guard — verify pipeline'ın SIFIR HALÜSİNASYON katmanı.

NLI yalnız doğrudan ÇELİŞKİ yakalar. Bu modül, [src:]-etiketli olduğu için
NLI/fuzzy'den geçen ama TEHLİKELİ olan iki yanlış-çıkarım sınıfını yakalar:

  1. Uydurma kanun adı — "İşçilik Kanunu" (gerçek: İş Kanunu). Kesin hata.
  2. Süre/eşik gerekçeli hak-reddi — "2 yıl kıdem için yetersiz" (md.14 min 1 yıl),
     "5 yıl altında tazminat verilmez" (uydurma eşik). Tehlikeli yanlış-çıkarım.

Gerçek Qwen 14B çıktısında gözlemlendi (2026-05-30). verify_node bu veto'yu
çağırır; bloklayıcı risk varsa fail-closed REJECT (CLAUDE.md §1).

NOT: production guard'ı (eval değil) — eval/answer_risk.py bunları re-export eder.
"""

from __future__ import annotations

import re

# --- Uydurma/yanlış kanun adları (kesin hata) ---
# Yalnız KESİN yanlış adlar: "-cilik/-lama" kökleri uydurma (Kanun/Yasa eki fark etmez);
# geçerli halk-dili adlar ("Borçlar Kanunu", "Tapu Kanunu") EKLENMEZ (false-positive önle).
_FABRICATED_LAW_RE = re.compile(
    r"\b(?:"
    r"İşçilik\s+(?:Kanunu|Yasası)|"     # gerçek: İş Kanunu
    r"Kiralama\s+(?:Kanunu|Yasası)|"    # gerçek: TBK kira hükümleri
    r"Tüketicilik\s+(?:Kanunu|Yasası)|"  # gerçek: Tüketicinin Korunması Hk. Kanun
    r"Trafik\s+Yasası|"                  # gerçek: Karayolları Trafik Kanunu
    r"Vergi\s+Yasası"                    # gerçek: VUK/GVK/KVK
    r")\b",
    re.IGNORECASE,
)

# --- Uydurma mahkeme dairesi atfı (imkânsız daire numarası) ---
# Türk yüksek mahkemelerinde (Yargıtay/Danıştay) daire sayısı tarihte ~23'ü GEÇMEDİ.
# Eşik > _MAX_CHAMBER muhafazakâr tavandır (FP=0): gerçek daireyi ASLA reddetmez,
# "99. Hukuk Dairesi" gibi uydurma atıfları yakalar. (Kesin sayı doğrulandıkça düşürülebilir.)
_MAX_CHAMBER = 30
_CHAMBER_RE = re.compile(
    r"\b(\d{1,3})\s*\.?\s*(?:Hukuk|Ceza|(?:İdari\s+)?Dava|Vergi\s+Dava)\s+Dairesi\b",
    re.IGNORECASE,
)

# --- Süre/eşik gerekçeli HAK-REDDİ (sıkı — denial kalıbı) ---
# Yalnız TEHLİKELİ kalıbı yakalar: süre/eşik gerekçe gösterip hak reddeden cümle.
# "1 yıl gerekir" gibi DOĞRU bilgilendirme yakalanmaz (false-positive minimize).
# `karşılamı(?!ş)` / `sağlamı(?!ş)`: olumsuz "karşılamıyor/sağlamıyor"u yakalar ama OLUMLU
# geçmiş "karşılamış/sağlamış" (= şartı KARŞILADI, hak doğar) cümlesini HARİÇ tutar. Aksi halde
# "1 yıl şartını karşılamış olabilirsiniz" gibi OLUMLU uygunluk cümlesi yanlışlıkla hak-reddi
# sanılıp tüm cevap veto ediliyordu → modelin aşırı-tereddütünün kök sebebi (gerçek-LLM 2026-06-04).
_DENIAL_VERB = (
    r"(?:karşılamı(?!ş)\w*|yetersiz|yeterli\s+değil|hak\s+kazanama\w*|kazanamaz|"
    r"verilmez|verilmeyebilir|alamaz\w*|doğmaz|sağlamı(?!ş)\w*|sağlamaz|"
    r"yeterli\s+olm\w*|geçerli\s+değil|mümkün\s+değil)"
)
# `altında`/`aşağı` (sayısız edat → "yükümlülük altında doğmaz" false-positive) ÇIKARILDI;
# yerine eşik DOĞRUDAN yakalanıyor — rakamsal süre ("5 yıl"), YAZIYLA süre ("bir yıl",
# "iki haftalık") ve PARA tutarı ("5.000 TL"). Eski "altında" bu yazıyla/para eşiklerini
# yakalıyordu (rakam `\d+` kaçırır); doğrudan eşik hem onları korur hem masum edatı eler
# (2026-06-04 calibration: 4 fabrike-red vakası + depozito false-veto birlikte çözülür).
_WRITTEN_NUM = r"(?:bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|yirmi|otuz|kırk|elli)"
_TIME_UNIT = r"(?:yıl|sene|ay|hafta|gün)\w*"
_DURATION_OR_THRESHOLD = (
    rf"(?:\d+\s*{_TIME_UNIT}"               # "5 yıl", "30 gün"
    rf"|{_WRITTEN_NUM}\s+{_TIME_UNIT}"      # "bir yıl", "iki haftalık"
    rf"|\d[\d.,]*\s*(?:tl|lira|₺)"          # "5.000 TL"
    rf"|süre\w*)"                            # "süreniz yetersiz"
)
_NEGATIVE_ELIGIBILITY_RE = re.compile(
    rf"{_DURATION_OR_THRESHOLD}.{{0,80}}?{_DENIAL_VERB}"
    rf"|{_DENIAL_VERB}.{{0,80}}?{_DURATION_OR_THRESHOLD}",
    re.IGNORECASE | re.DOTALL,
)

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def fabricated_law_names(text: str) -> list[str]:
    """Bilinen uydurma/yanlış kanun adlarını döndür (kesin hata)."""
    return [m.group(0) for m in _FABRICATED_LAW_RE.finditer(text)]


def negative_eligibility_claims(text: str) -> list[str]:
    """Süre/eşik gerekçesiyle HAK REDDEDEN cümleler (sıkı, veto için).

    "2 yıl ... karşılamıyor", "5 yıl altında ... verilmeyebilir" gibi TEHLİKELİ
    yanlış-çıkarımları yakalar; "1 yıl gerekir" gibi doğru bilgilendirmeyi
    yakalamaz (false-positive minimize).
    """
    flags = []
    for sent in _SENT_SPLIT_RE.split(text):
        if _NEGATIVE_ELIGIBILITY_RE.search(sent):
            flags.append(sent.strip()[:160])
    return flags


# --- FABRİKE-eşik (kaynak-temelli, DETERMİNİSTİK) ---
# "Sıfır halüsinasyon"un en zayıf noktası: süre/eşik gerekçeli hak-reddinin DOĞRU
# (kaynakta var: "kıdem için en az 1 yıl" → "1 yılın altında kazanamaz" DOĞRU) vs
# FABRİKE (kaynakta YOK: "5 yıldan az tazminat verilmez" = uydurma eşik) ayrımı.
# Çözüm: iddiadaki SAYISAL eşiği getirilen KAYNAK metinleriyle karşılaştır.
# İddia-eşiği hiçbir kaynakta geçmiyorsa → FABRİKE (uydurma eşik → veto).
# Kaynakta geçiyorsa → TRUE (doğru bilgilendirme → vetolanmaz, false-positive önlenir).
# Türkçe sayı-kelimeleri de yakalanır ("bir yıl" = "1 yıl") → rakam/kelime eşiği eşleşir.
_NUM_WORDS = {"bir": "1", "iki": "2", "üç": "3", "dört": "4", "beş": "5",
              "altı": "6", "yedi": "7", "sekiz": "8", "dokuz": "9", "on": "10"}
_NUM_DURATION_RE = re.compile(
    r"\b(\d+|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on)\s*(yıl|sene|ay|hafta|gün)",
    re.IGNORECASE,
)
_UNIT_CANON = {"yıl": "yıl", "sene": "yıl", "ay": "ay", "hafta": "hafta", "gün": "gün"}


def _norm_thresholds(text: str) -> set[tuple[str, str]]:
    """Metindeki süre-eşiklerini (sayı, kanonik-birim) kümesi yap. Sayı-kelime → rakam,
    yıl/sene → yıl normalize → '1 yıl' ile 'bir sene' aynı eşik sayılır."""
    out: set[tuple[str, str]] = set()
    for m in _NUM_DURATION_RE.finditer(text):
        num = _NUM_WORDS.get(m.group(1).lower(), m.group(1))
        unit = _UNIT_CANON.get(m.group(2).lower(), m.group(2).lower())
        out.add((num, unit))
    return out


# Bir süre-eşiğinin "kaynakta-temelli DOĞRU" sayılması için, eşiğin GEÇTİĞİ snippet bir
# UYGUNLUK-ASGARİSİ bağlamı taşımalı. Aksi halde getirilen ilgisiz bir snippet'teki süre
# ('alacak zamanaşımı 5 yıl', '5 yıl hapis') uydurma bir hak-reddi eşiğini ('5 yıl altında
# hak kazanamazsınız') AKLAYIP veto'dan kaçırır (çapraz-kontaminasyon). Bu nedenle eşik
# küresel havuzdan DEĞİL, yalnız asgari-gereklilik bağlamı taşıyan snippet'lerden alınır.
_REQUIREMENT_MARKERS = (
    "en az", "asgari", "minimum", "şart", "gerek", "dolduran", "doldur",
    "dolması", "tamamla", "hak kazan", "aranır", "şartı", "koşul",
)


def _grounded_thresholds(source_texts: list[str]) -> set[tuple[str, str]]:
    """Yalnız UYGUNLUK-ASGARİSİ bağlamı taşıyan snippet'lerdeki süre-eşikleri döndür.

    Eşik, geçtiği snippet'in asgari-gereklilik bağlamından gelir (küresel havuzdan değil)
    → ilgisiz bir snippet'teki süre uydurma bir eşiği aklayamaz (kırmızı-çizgi güvenliği).
    Hiçbir snippet gereklilik bağlamı taşımıyorsa boş döner → fail-closed (eşik uydurma
    sayılır, veto edilir) — CLAUDE.md §1 doğrulanamazsa reddedilir ilkesiyle uyumlu.
    """
    grounded: set[tuple[str, str]] = set()
    for snip in source_texts:
        low = snip.lower()
        if any(m in low for m in _REQUIREMENT_MARKERS):
            grounded |= _norm_thresholds(low)
    return grounded


def fabricated_eligibility_threshold(text: str, source_texts: list[str]) -> list[str]:
    """Hak-reddi cümlesindeki SAYISAL eşik getirilen kaynaklarda YOK ise FABRİKE döner.

    DETERMİNİSTİK (prompt/regex tahminİ değil): iddia-eşiği vs kaynak-eşiği karşılaştırır.
    - "5 yıldan az tazminat verilmez" + kaynak yalnız "1 yıl" diyorsa → '5 yıl' FABRİKE.
    - "1 yılın altında kıdem doğmaz" + kaynak "en az 1 yıl" diyorsa → '1 yıl' DOĞRU (boş).
    Sayısal eşiği olmayan hak-reddi (örn "süreniz yetersiz") bu detektörü ATLAR — genel
    negative_eligibility_claims + diğer katmanlar onu ele alır. source_texts boşsa boş döner
    (temellendirme yapılamaz → bu detektör sessiz; baseline güvenli).
    """
    if not source_texts:
        return []
    source_thresholds = _grounded_thresholds(source_texts)  # bağlam-kapsamlı (havuz değil)
    flags: list[str] = []
    for sent in _SENT_SPLIT_RE.split(text):
        if not _NEGATIVE_ELIGIBILITY_RE.search(sent):
            continue
        claim_thresholds = _norm_thresholds(sent.lower())
        if not claim_thresholds:
            continue  # sayısal eşik yok → bu detektör kapsamı dışı
        if any(th not in source_thresholds for th in claim_thresholds):
            flags.append(sent.strip()[:160])
    return flags


def fabricated_citation_claims(text: str) -> list[str]:
    """İmkânsız mahkeme dairesi atıflarını döndür (örn '99. Hukuk Dairesi').

    Yalnız _MAX_CHAMBER'ı aşan numaraları işaretler → gerçek daire (1–~23) asla
    yanlışlıkla bloklanmaz; uydurma yüksek-numaralı atıflar yakalanır.
    """
    flags: list[str] = []
    for m in _CHAMBER_RE.finditer(text):
        if int(m.group(1)) > _MAX_CHAMBER:
            flags.append(m.group(0).strip())
    return flags


# --- İmkânsız madde numarası (kesin hata → veto) ---
# Hiçbir TR kanununda olamayacak madde no (en büyük TMK ~1030 madde). > _ABSURD_ARTICLE_MAX
# muhafazakâr tavan (FP=0): gerçek maddeyi (1–~1030) ASLA reddetmez; 'madde 5000' gibi uydurma
# atıfları yakalar. (Denetim 2026-06-04: eval-only iken production veto'ya terfi — layer1_rules
# 1≤no≤99999'u syntactic geçerli sayıyordu, 'madde 5000' veto'suz geçebiliyordu.)
_ABSURD_ARTICLE_MAX = 1100
_ARTICLE_RE = re.compile(r"\bmadde\s*(\d{1,5})\b", re.IGNORECASE)


def implausible_article_numbers(text: str) -> list[str]:
    """Hiçbir TR kanununda olamayacak madde no (örn 'madde 5000') → kesin hata (veto)."""
    return [m.group(0).strip() for m in _ARTICLE_RE.finditer(text)
            if int(m.group(1)) > _ABSURD_ARTICLE_MAX]


def _grounded_true_eligibility(text: str, source_texts: list[str]) -> set[str]:
    """Hak-reddi cümlelerinden TÜM sayısal eşiği kaynakta GEÇENLER (DOĞRU) → veto muafı.

    Eşiksiz ('süreniz yetersiz') veya FABRİKE (kaynakta-olmayan eşikli) cümleler kümede
    DEĞİL → vetolanır. Yalnız kaynakta-temellendirilmiş DOĞRU bilgilendirmeyi serbest bırakır.
    """
    src_th = _grounded_thresholds(source_texts)  # bağlam-kapsamlı (ilgisiz snippet aklayamaz)
    out: set[str] = set()
    for sent in _SENT_SPLIT_RE.split(text):
        if not _NEGATIVE_ELIGIBILITY_RE.search(sent):
            continue
        claim_th = _norm_thresholds(sent.lower())
        if claim_th and all(th in src_th for th in claim_th):
            out.add(sent.strip()[:160])
    return out


def verify_risk_veto(text: str, source_texts: list[str] | None = None) -> tuple[bool, list[str]]:
    """Verify pipeline veto kararı: cevapta BLOKLAYICI içerik-riski var mı?

    Bloklayıcı (fail-closed → reject) — yalnız YÜKSEK-KESİNLİKLİ sınıflar:
      - Uydurma kanun adı (kesin hata)
      - Süre/eşik gerekçeli hak-reddi (tehlikeli yanlış-çıkarım)
      - İmkânsız mahkeme dairesi atfı (uydurma kaynak)

    source_texts VERİLİRSE (getirilen mevzuat/emsal snippet'leri): süre/eşik hak-reddinin
    KAYNAKTA-TEMELLİ DOĞRU olanı muaf tutulur ('en az 1 yıl' kaynaktayken '1 yılın altında
    kazanamaz' DOĞRU → vetolanmaz; valid cevap red-flakiness'i giderilir). FABRİKE (kaynakta
    olmayan eşik), eşiksiz hak-reddi ve kaynaksız çağrı → HÂLÂ veto (kırmızı çizgi korunur).
    Detektör precision=1.0 (eligibility_eval) → DOĞRU muafiyeti güvenli.

    Returns: (bloklanmalı_mı, gerekçe_listesi). CLAUDE.md §1: doğrulanamazsa REDDEDİLİR.
    """
    reasons: list[str] = []
    for law in fabricated_law_names(text):
        reasons.append(f"uydurma kanun adı: {law}")
    grounded_true = _grounded_true_eligibility(text, source_texts) if source_texts else set()
    for sent in negative_eligibility_claims(text):
        if sent in grounded_true:
            continue  # kaynakta-temelli DOĞRU bilgilendirme → vetolanma
        reasons.append(f"süre/eşik gerekçeli hak-reddi: {sent}")
    for cite in fabricated_citation_claims(text):
        reasons.append(f"imkânsız mahkeme dairesi atfı: {cite}")
    for art in implausible_article_numbers(text):
        reasons.append(f"imkânsız madde numarası: {art}")
    return (bool(reasons), reasons)
