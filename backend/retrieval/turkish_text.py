"""Türkçe metin normalleştirme + stemming (Sprint-4 W1).

Türkçe agglutinatif bir dildir — "kıdem tazminat", "kıdemin tazminatına",
"kıdemli tazminatlar" hepsi aynı kavramı kapsar. BGE-M3 BPE tokenizer'ı
çoğunlukla iyi parçalar ama kısa formlar arasında eşitlik kuramaz.

Bu modül:
1. snowballstemmer ile Türkçe stem (`Snowball.algorithm("turkish")`).
2. ASCII-fold normalize (eşleşme genişletmek için opsiyonel).
3. Stopword listesi (Türkçe hukuki bağlam için kısaltılmış).
4. `morphological_variants()` — bir köke birkaç son ek varyasyonu üretir;
   multi_query paraphrase fallback'i olarak kullanılır.

Kullanım:
    from retrieval.turkish_text import stem_text, keyword_overlap

    stems = stem_text("Kıdem tazminatı nasıl hesaplanır?")
    # → ["kıdem", "tazminat", "hesapla"]

    overlap = keyword_overlap(answer, expected_keywords, use_stem=True)
"""

from __future__ import annotations

import re
from functools import lru_cache

import structlog

from core.text import tr_lower  # tek kanonik (denetim #40); aşağıda re-export

log = structlog.get_logger()

# Hukuki bağlamda anlam taşımayan ama yüksek-frekanslı Türkçe kelimeler.
# Liste bilinçli kısa tutuldu — "kanun", "madde" gibi hukuki yer-tutucular
# DAHIL DEĞIL (anlam taşırlar). Sadece dil bağlamı.
_TURKISH_STOPWORDS: frozenset[str] = frozenset({
    "ve", "veya", "ya", "ile", "ki", "için", "gibi", "kadar", "ama",
    "fakat", "ancak", "böyle", "şöyle", "bu", "şu", "o", "bir", "birkaç",
    "her", "hiç", "bana", "sana", "ona", "bize", "size", "onlara",
    "ben", "sen", "biz", "siz", "onlar",
    "mi", "mu", "mı", "mü", "de", "da", "ne", "nasıl", "niye", "neden", "nerede", "nereden", "ne zaman",
})

# Punctuation + symbol stripper — regex daha hızlı
_WORD_SPLIT_RE = re.compile(r"[^\w]+", re.UNICODE)


# tr_lower core/text.py'de tanımlı (yukarıda import edildi) — tek kanonik; bu modülde
# (stem_word/tokenize/keyword_overlap…) ve `from retrieval.turkish_text import tr_lower`
# kullanıcılarında (eval/answer_risk) geriye-uyumlu çalışır.


def _get_stemmer():
    """Lazy import + cache — snowballstemmer optional dependency."""
    try:
        from snowballstemmer import stemmer  # type: ignore[import-untyped]
        return stemmer("turkish")
    except ImportError:
        log.warning("snowballstemmer_unavailable")
        return None


_STEMMER = _get_stemmer()


@lru_cache(maxsize=4096)
def stem_word(word: str) -> str:
    """Tek kelimeyi Türkçe stem'le. Stemmer yoksa lower() döner."""
    if not word:
        return ""
    lo = tr_lower(word).strip()
    if _STEMMER is None:
        return lo
    return _STEMMER.stemWord(lo)


def tokenize(text: str) -> list[str]:
    """Metni Türkçe-uyumlu tokenlere böl; stopword'leri at."""
    if not text:
        return []
    parts = _WORD_SPLIT_RE.split(tr_lower(text))
    return [p for p in parts if p and p not in _TURKISH_STOPWORDS]


def stem_text(text: str) -> list[str]:
    """Metni stem'lenmiş token listesine çevir (stopword filtreli)."""
    return [stem_word(tok) for tok in tokenize(text) if tok]


_STEM_PREFIX_MIN = 4   # prefix-overlap için minimum eşleşen önek uzunluğu


def _stem_prefix_match(target: str, candidates: set[str]) -> bool:
    """Türkçe stemmer agresif (`"kıdem"→"kıde"`); exact match kaçırılır.

    Yumuşak match: target ile candidate'lardan biri arasında en az
    `_STEM_PREFIX_MIN` karakter ortak başlangıç → match. Çok kısa stem'ler
    (`"de"`, `"da"`) için yalnız exact match.
    """
    if len(target) < _STEM_PREFIX_MIN:
        return target in candidates
    for cand in candidates:
        if not cand:
            continue
        # Daha uzun olan diğerinin prefix'i mi? (en az min ortak)
        if cand == target:
            return True
        common = min(len(cand), len(target))
        if common >= _STEM_PREFIX_MIN and cand[:common] == target[:common]:
            return True
    return False


def keyword_overlap(
    answer_text: str,
    expected_keywords: list[str],
    *,
    use_stem: bool = True,
) -> float:
    """Türkçe morfoloji-aware keyword recall.

    "kıdem tazminatı" beklerken cevap "kıdemin tazminatları" verirse,
    stem-aware match ikisini de eşler. Snowball Türkçe stemmer agresif
    olduğu için (örn. `"kıdem"→"kıde"`) prefix-overlap stratejisi
    kullanılır — en az 4 ortak başlangıç karakteri yeterli.
    `use_stem=False` ise basit lower() substring match (geri uyumluluk).

    Returns:
        Recall ∈ [0.0, 1.0] — expected_keywords'in kaçı cevapta bulundu.
    """
    if not expected_keywords:
        return 0.0
    if not answer_text:
        return 0.0

    if use_stem:
        answer_stems = set(stem_text(answer_text))
        n_hit = 0
        for kw in expected_keywords:
            kw_stems = stem_text(kw)
            # Beklenen kw çok-token ise hepsi cevap stem'lerinde varsa hit
            if kw_stems and all(_stem_prefix_match(s, answer_stems) for s in kw_stems):
                n_hit += 1
        return n_hit / len(expected_keywords)

    # Plain substring (Türkçe-doğru lower)
    low_ans = tr_lower(answer_text)
    n_hit = sum(1 for kw in expected_keywords if tr_lower(kw) in low_ans)
    return n_hit / len(expected_keywords)


def query_coverage(question: str, texts: list[str]) -> float:
    """Sorgu içerik-kelimelerinin (stopword'süz) metinlerce EN İYİ kapsanma oranı [0-1].

    CRAG canlı-fallback tetikleyicisi için (2026-06-10 emsal-bench bulgusu):
    cross-encoder skoru 'corpus'ta yok' sinyali DEĞİL — 24/24 yanlış alarm + tek
    gerçek boşlukta 0.802 skor. Bu sinyal sorgunun kelimeleri dönen kararlarda hiç
    geçmiyorsa (kapsama düşük) 'alakasız sonuç' der; skor kalibrasyonundan bağımsız,
    stem-aware. Sınırı bilinir: yanlış ALT-KONU kapsama yüksekken yakalanamaz
    (o boşluğun çözümü corpus kürasyonu, sinyal değil).
    """
    q_words = tokenize(question)
    if not q_words or not texts:
        return 0.0
    return max(keyword_overlap(t, q_words) for t in texts)


def morphological_variants(question: str, max_variants: int = 3) -> list[str]:
    """Soru için Türkçe morfolojik varyasyon üret (LLM-siz).

    Multi-query paraphrase fallback'i. LLM timeout / unavailable durumunda
    deterministic alternatif sorgular sağlar. Her variant orijinal kelimeleri
    farklı son ek formlarıyla yazar.

    Strateji:
        1) Stem'le → kökleri çıkar
        2) Stemli formu da arama sorgusu olarak ekle (BPE tokenizer kökü
           ayrı match etmeye çalışacak → recall +)
        3) Birkaç yaygın ek (-lar, -lik, -leri) ile genişlet

    Returns:
        En fazla max_variants farklı sorgu (orijinal hariç).
    """
    if not question.strip():
        return []
    stems = stem_text(question)
    if not stems:
        return []

    variants: list[str] = []

    # Varyant 1: tüm kelimeleri stem formuna indir (en kısa form)
    stem_form = " ".join(stems)
    if stem_form and stem_form != tr_lower(question):
        variants.append(stem_form)

    # Varyant 2: çoğul "-lar/-ler" — son kelimeye ek
    if len(variants) < max_variants and len(stems) >= 2:
        last_stem = stems[-1]
        # Türkçe ünlü uyumu: son ünlü kalın → -lar, ince → -ler
        plural_suffix = "lar" if _last_vowel_back(last_stem) else "ler"
        plural_form = " ".join(stems[:-1] + [last_stem + plural_suffix])
        variants.append(plural_form)

    # Varyant 3: "-lık/-lik/-luk/-lük" abstract noun (4-yönlü ünlü uyumu)
    if len(variants) < max_variants and stems:
        first_stem = stems[0]
        nominal_suffix = _lik_suffix(first_stem)
        nominal_form = " ".join([first_stem + nominal_suffix] + stems[1:])
        if nominal_form != stem_form:
            variants.append(nominal_form)

    return variants[:max_variants]


_VOWELS = "aeıioöuü"


def _last_vowel(word: str) -> str:
    """Kelimedeki son ünlüyü döndür (yoksa 'a' — kalın default)."""
    for ch in reversed(word):
        if ch in _VOWELS:
            return ch
    return "a"


def _last_vowel_back(word: str) -> bool:
    """Son ünlü kalın mı (a, ı, o, u)? Türkçe ünlü uyumu için."""
    return _last_vowel(word) in "aıou"


# --------------------------------------------------------------------------
#  Hukuki eşanlamlılık genişletmesi (deterministik — LLM'siz)
# --------------------------------------------------------------------------
#
# Vatandaş dili ↔ kanun jargonu köprüsü. "depozitomu vermiyor" ile "kira
# teminatı iade edilmedi" aynı semantik soru ama farklı kelimeler — dense
# embedder bunu kısmen yakalar, ama deterministik genişletme recall'u LLM
# multi-query'ye (timeout'a düşebilir) bağımlı olmadan artırır.
#
# Kapsam: CLAUDE.md §4 — tüketici + iş + kira hukuku + genel hukuki terimler.
# Her grup KARŞILIKLI eşanlamlı ifadelerden oluşur; bir soruda grubun herhangi
# bir üyesi geçerse diğer üyelerle değiştirerek varyant sorgu üretilir.
LEGAL_SYNONYMS: tuple[tuple[str, ...], ...] = (
    # --- İş hukuku ---
    ("kıdem tazminatı", "iş sonu tazminatı", "işten ayrılma tazminatı"),
    ("ihbar tazminatı", "bildirim tazminatı", "ihbar öneli tazminatı"),
    ("işten çıkarma", "iş akdinin feshi", "işe son verme", "işten atılma"),
    ("haksız fesih", "geçersiz fesih", "haksız işten çıkarma"),
    ("fazla mesai", "fazla çalışma", "fazla mesai ücreti"),
    ("işçi alacağı", "işçilik alacakları", "ödenmeyen ücret"),
    ("yıllık izin", "yıllık ücretli izin", "izin ücreti"),
    # --- Kira hukuku ---
    ("depozito", "güvence bedeli", "kira teminatı", "depozito iadesi"),
    ("ev sahibi", "kiraya veren", "mülk sahibi"),
    ("tahliye", "evden çıkarma", "kiracının tahliyesi", "boşaltma"),
    ("kira sözleşmesi", "kira kontratı", "kira akdi"),
    ("kira artışı", "kira zammı", "kira bedeli artışı"),
    # --- Tüketici hukuku ---
    ("ayıplı mal", "kusurlu ürün", "defolu ürün", "arızalı ürün"),
    ("cayma hakkı", "sözleşmeden dönme", "vazgeçme hakkı"),
    ("iade", "geri ödeme", "ücret iadesi", "para iadesi"),
    ("garanti", "garanti belgesi", "garanti kapsamı"),
    ("tüketici hakem heyeti", "hakem heyeti", "tüketici hakları"),
    ("mesafeli satış", "internetten alışveriş", "online satış"),
    # --- Genel hukuki terimler ---
    ("ihtarname", "ihtar", "resmi uyarı", "noter ihtarı"),
    ("sözleşme", "kontrat", "mukavele", "akit"),
    ("tazminat", "zarar tazmini", "zararın giderilmesi"),
    ("dava açmak", "dava etmek", "yargıya başvurmak"),
    ("zamanaşımı", "hak düşürücü süre", "dava açma süresi"),
    ("temerrüt", "borçlu temerrüdü", "ödememe"),
)


@lru_cache(maxsize=1)
def _synonym_index() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Eşanlam araması için (ifade_lower, grup) çiftleri — uzun ifade önce.

    Uzun ifade önce sıralanır ki "kira sözleşmesi" "kira"dan önce eşleşsin
    (prefix-collision'ı önler).
    """
    pairs: list[tuple[str, tuple[str, ...]]] = []
    for group in LEGAL_SYNONYMS:
        lowered = tuple(tr_lower(m) for m in group)
        for member in lowered:
            pairs.append((member, lowered))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return tuple(pairs)


def expand_with_synonyms(question: str, max_variants: int = 3) -> list[str]:
    """Soruda geçen hukuki ifadeleri eşanlamlılarıyla değiştirip varyant üret.

    Deterministik (LLM'siz). "depozitomu iade etmiyor" → "güvence bedeli iade
    etmiyor", "kira teminatı iade etmiyor". multi_query'nin RRF kollarını
    LLM'e bağımlı olmadan zenginleştirir.

    Returns:
        En fazla max_variants benzersiz varyant (orijinal hariç). İfade
        bulunamazsa boş liste.
    """
    if not question.strip():
        return []
    q_low = tr_lower(question)
    variants: list[str] = []
    seen: set[str] = {q_low}
    for member, group in _synonym_index():
        if member not in q_low:
            continue
        for alt in group:
            if alt == member:
                continue
            variant = q_low.replace(member, alt)
            if variant not in seen:
                seen.add(variant)
                variants.append(variant)
            if len(variants) >= max_variants:
                return variants
    return variants


def _lik_suffix(word: str) -> str:
    """-lık/-lik/-luk/-lük — Türkçe 4-yönlü ünlü uyumu (büyük ünlü uyumu).

    Eski kod iki dalda da "lik" üretiyordu (kopyala-yapıştır bug) → "kıdemlik"
    yerine "kıdemlik" (doğru) ama "kiralik" gibi yanlış formlar. Doğru: son
    ünlüye göre lık (a/ı) · lik (e/i) · luk (o/u) · lük (ö/ü).
    """
    v = _last_vowel(word)
    if v in "aı":
        return "lık"
    if v in "ei":
        return "lik"
    if v in "ou":
        return "luk"
    return "lük"  # ö, ü


__all__ = (
    "LEGAL_SYNONYMS",
    "expand_with_synonyms",
    "keyword_overlap",
    "morphological_variants",
    "stem_text",
    "stem_word",
    "tokenize",
    "tr_lower",
)
