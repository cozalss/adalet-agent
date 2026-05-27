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


def tr_lower(s: str) -> str:
    """Türkçe-doğru küçük harfe çevirme.

    Python `str.lower()` Türkçe İ/I'yı YANLIŞ çevirir:
      "İ".lower() → "i̇" (i + U+0307 combining dot above) — "i" ile eşleşmez
      "I".lower() → "i"  (Türkçe'de "ı" olmalı)
    Hukuk metni İ/I dolu (İş, İcra, İdari, İhtarname, IK/İK). Yanlış casefold
    "İş Kanunu" ↔ "iş kanunu" token'larını ayırıp recall'u sessizce düşürür.
    Önce İ→i, I→ı eşle, sonra kalan harfleri standart lower() ile indir.
    """
    return s.replace("İ", "i").replace("I", "ı").lower()


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
    "keyword_overlap",
    "morphological_variants",
    "stem_text",
    "stem_word",
    "tokenize",
    "tr_lower",
)
