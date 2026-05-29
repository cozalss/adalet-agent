"""Smalltalk (sohbet) tespiti — selamlaşma/teşekkür/veda/kimlik sorularına
LLM çağırmadan, anında, dostça yanıt.

Neden kural-tabanlı (LLM değil):
  - "merhaba" gibi girdiler hukuk sorusu değildir; triaj LLM'i bunları "unknown"
    döndürür ve finalize soğuk "avukata danışın" reddi basardı (kötü UX).
  - Sohbet yanıtında hiçbir hukuki İDDİA yok → SIFIR HALÜSİNASYON riski yok.
  - LLM çağrısı atlanır → ~3 sn yerine anında yanıt.

Tasarım kararı: yalnız KISA ve net sohbet girdilerini yakalar. "merhaba, kira
sözleşmem hakkında..." gibi selamla başlayan GERÇEK sorular hukuki ipucu (kelime
veya rakam) içerdiğinden buradan GEÇMEZ → normal triaj LLM'ine gider (doğru).
Yanlış-negatif güvenli: yakalayamazsak en kötü ihtimalle normal akışa düşer.
"""

from __future__ import annotations

import re

# Sohbet kategorileri — finalize bunlara göre değil, hazır metni doğrudan basar.
SmalltalkCategory = str  # "greeting" | "thanks" | "farewell" | "capability" | "identity"

# Tam-eşleşen sohbet kalıpları (normalize edilmiş: küçük harf, noktalama yok).
_GREETINGS: frozenset[str] = frozenset({
    "merhaba", "merhabalar", "selam", "selamlar", "selamün aleyküm",
    "slm", "mrb", "günaydın", "iyi günler", "iyi akşamlar", "iyi geceler",
    "hey", "hello", "hi", "hayırlı günler", "hayırlı sabahlar",
    "naber", "nasılsın", "nasilsin", "ne haber",
})
_THANKS: frozenset[str] = frozenset({
    "teşekkürler", "teşekkür ederim", "teşekkür", "teşekkurler",
    "sağ ol", "sağol", "sağ olun", "sağolun", "eyvallah",
    "çok teşekkür ederim", "çok teşekkürler", "tşk", "tşkler", "teşekür ederim",
})
_FAREWELL: frozenset[str] = frozenset({
    "görüşürüz", "hoşça kal", "hoşçakal", "güle güle", "kendine iyi bak",
    "bay bay", "iyi günler dilerim", "görüşmek üzere", "hoşçakalın",
})
_CAPABILITY: frozenset[str] = frozenset({
    "ne yapabilirsin", "neler yapabilirsin", "ne yaparsın", "ne işe yararsın",
    "nasıl çalışırsın", "nasıl çalışıyorsun", "nasıl yardımcı olabilirsin",
    "ne yapıyorsun", "neler yapabiliyorsun", "bana nasıl yardımcı olabilirsin",
    "ne yapabiliyorsun", "yardım", "yardım et", "ne konularda yardımcı olursun",
})
_IDENTITY: frozenset[str] = frozenset({
    "kimsin", "sen kimsin", "nesin", "sen nesin", "adın ne", "ismin ne",
    "sen bir bot musun", "robot musun", "yapay zeka mısın", "sen nesin sen",
})

# Kategori → hazır yanıt. Hiçbiri SOMUT hukuki iddia içermez (madde/karar yok),
# yalnız sistemin kapsamını anlatır ve kullanıcıyı soru sormaya yönlendirir.
_REPLIES: dict[str, str] = {
    "greeting": (
        "Merhaba! Ben ADALET, Türkçe hukuk asistanınız. Tüketici, iş, kira, icra, "
        "trafik, vergi, tapu ve idari hukuk konularında; gerçek mevzuat ve Yargıtay "
        "kararlarına dayanarak sorularınızı yanıtlayabilirim.\n\n"
        "Yaşadığınız durumu birkaç cümleyle anlatmanız yeterli. Örneğin: "
        "\"Kira depozitomu ev sahibi iade etmiyor, ne yapabilirim?\""
    ),
    "capability": (
        "Size şu konularda yardımcı olabilirim:\n\n"
        "- Tüketici, iş, kira, icra, trafik, vergi, tapu ve idari hukuk sorularını "
        "yanıtlama\n"
        "- İlgili kanun maddelerini ve Yargıtay kararlarını bulup gösterme\n"
        "- Gerektiğinde resmi dilekçe taslağı hazırlama\n\n"
        "Her yanıtı gerçek mevzuata dayandırır, kullandığım kaynakları gösteririm. "
        "Durumunuzu anlatın, birlikte bakalım."
    ),
    "identity": (
        "Ben ADALET — avukata kolayca erişemeyen vatandaşlar için geliştirilen, "
        "Türkçe hukuk sorularını gerçek mevzuat ve Yargıtay kararlarıyla yanıtlayan "
        "bir yapay zeka asistanıyım. Verdiğim her bilgiyi doğrulanmış kaynaklara "
        "dayandırırım.\n\nHangi konuda yardımcı olabilirim?"
    ),
    "thanks": (
        "Rica ederim. Başka bir hukuki sorunuz olursa çekinmeden yazabilirsiniz."
    ),
    "farewell": (
        "Görüşmek üzere. Hukukla ilgili aklınıza takılan her şeyde buradayım, "
        "kendinize iyi bakın."
    ),
}

# Sohbet adayını GERÇEK hukuk sorusundan ayıran ipuçları. Biri varsa smalltalk
# DEĞİL (örn. "selam kira sorum var" → "kira" ipucu → normal triaj'a gider).
# Geniş tutulur: yanlış-pozitif ipucu güvenli (en fazla LLM triaj'a düşer).
_LEGAL_HINT_TOKENS: tuple[str, ...] = (
    "madde", "kanun", "hak", "tazminat", "kira", "işçi", "işten", "işveren",
    "dava", "sözleş", "borç", "icra", "ceza", "vergi", "tapu", "trafik",
    "ihtar", "dilekçe", "mahkeme", "avukat", "depozito", "fatura", "iade",
    "garanti", "şikayet", "şikâyet", "boşan", "nafaka", "miras", "ceza",
    "haciz", "temyiz", "itiraz", "fesih", "noter", "senet", "kefil",
)

# Türkçe noktalı/noktasız I sorununu çöz (str.lower "İ"→"i̇" combining dot üretir).
def _tr_lower(text: str) -> str:
    return text.replace("I", "ı").replace("İ", "i").lower()


# Harf (Türkçe dahil), rakam ve boşluk dışını boşluğa çevir → emoji/noktalama temiz.
_NORM_STRIP_RE = re.compile(r"[^0-9a-zçğıöşü\s]", re.UNICODE)

# En fazla bu kadar kelimelik girdiler sohbet adayı sayılır; uzunlar gerçek soru.
_MAX_SMALLTALK_WORDS = 6


def _normalize(text: str) -> str:
    """Karşılaştırma için: Türkçe-küçült, noktalama/emoji sil, boşlukları sıkıştır."""
    cleaned = _NORM_STRIP_RE.sub(" ", _tr_lower(text))
    return " ".join(cleaned.split())


def _has_legal_hint(norm: str) -> bool:
    """Rakam veya hukuki anahtar kelime içeriyorsa gerçek soru olabilir."""
    if any(ch.isdigit() for ch in norm):
        return True
    return any(tok in norm for tok in _LEGAL_HINT_TOKENS)


def detect_smalltalk(question: str) -> SmalltalkCategory | None:
    """Soru saf bir sohbet girdisiyse kategorisini, değilse None döndür.

    Yalnız kısa ve net girdileri yakalar. Hukuki ipucu (kelime/rakam) içeren ya
    da uzun girdiler None döner → normal triaj akışına gider.
    """
    norm = _normalize(question)
    if not norm:
        return None

    words = norm.split()
    if len(words) > _MAX_SMALLTALK_WORDS:
        return None  # uzun girdi = gerçek soru (selamla başlasa bile)

    # Tam-eşleşme (en güvenilir) — sıra: en spesifik kategoriler önce.
    if norm in _THANKS:
        return "thanks"
    if norm in _FAREWELL:
        return "farewell"
    if norm in _CAPABILITY:
        return "capability"
    if norm in _IDENTITY:
        return "identity"
    if norm in _GREETINGS:
        return "greeting"

    # Selamla başlayan kısa girdi ("merhaba dostum", "selam") — hukuki ipucu yoksa.
    if not _has_legal_hint(norm):
        for greet in _GREETINGS:
            if norm == greet or norm.startswith(f"{greet} "):
                return "greeting"
    return None


def smalltalk_reply(category: SmalltalkCategory) -> str:
    """Kategoriye göre hazır dostça yanıt. Bilinmeyen kategori → genel selam."""
    return _REPLIES.get(category, _REPLIES["greeting"])


__all__ = ("SmalltalkCategory", "detect_smalltalk", "smalltalk_reply")
