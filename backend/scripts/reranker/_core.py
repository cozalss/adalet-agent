"""Faz-4 reranker pipeline'ı — SAF çekirdek (ağ/model GEREKMEZ, birim-test edilir).

Konuşma-dili sentezli Türkçe reranker triplet üretiminin tüm deterministik mantığı
burada: kapsam-filtresi (8 sivil alan; ceza/aile ELE), few-shot konuşma-dili soru
prompt'u, sentez çıktısı temizleme, round-trip filtre kararı, dedup, train/val split,
etiketli-çift şekillendirme. I/O + LLM + embedder çağrıları ayrı script'lerde (bunu
import eder). Desen: eval/answer_risk.py + verifier_layers.py (saf-çekirdek ayrımı).

KIRMIZI ÇİZGİ (CLAUDE.md §1, §4): sistem yalnız 8 SİVİL alanda çalışır — ceza ve aile
hukuku KAPSAM DIŞI. Eğitim verisinden de bunları eler. LLM yalnız SORU üretir; pozitif
kaynak (madde/karar metni) GERÇEK datasetten/fetch'ten gelir, uydurulmaz.
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass

# 8 sivil hukuk alanı (triaj ile ORTAK; agents/state.Domain ile uyumlu).
CIVIL_DOMAINS = ("tuketici", "isHukuku", "kira", "icra", "trafik", "vergi", "tapu", "idari")

# KAPSAM-DIŞI işaretçiler — bu örnekler eğitim setinden ELENİR (ceza + aile hukuku).
# Dikkat: "ceza" tek başına SİVİL olabilir (idari/trafik/vergi para cezası) → yalnız
# CEZA-HUKUKUNA ÖZGÜ işaretçiler. "nafaka/boşanma" → aile; sistemin kırmızı çizgisi.
_OUT_OF_SCOPE_MARKERS: tuple[str, ...] = (
    # --- Ceza hukuku (adli) ---
    "sanik", "musteki", "iddianame", "beraat", "mahkumiyet", "hapis cezas",
    "adli para cezas", "tutuklan", "tutuklu", "gozalti", "savcilik", "savcinin",
    "suc duyuru", "kasten oldur", "kasten yaralama", "hirsizlik", "dolandiricilik suc",
    "uyusturucu", "turk ceza kanunu", "tck madde", "tck m.", "agir ceza",
    # --- Aile hukuku ---
    "bosanma", "bosan", "nafaka", "velayet", "velâyet", "nisan bozma", "mehir",
    "evlat edin", "soybag", "babalik dava", "evlilik birlig", "mal rejim",
    "katilma alacag", "iddet muddet", "nikah",
)

# Alan etiketleme ipuçları (best-effort; stratifikasyon için, filtre için DEĞİL).
_DOMAIN_HINTS: dict[str, tuple[str, ...]] = {
    "kira": ("kira", "kiraci", "ev sahib", "mecur", "tahliye", "depozito", "kontrat"),
    "isHukuku": ("isci", "isveren", "kidem", "ihbar tazminat", "fazla mesai", "is akdi",
                 "issizlik", "is kanunu", "sgk prim", "ise iade"),
    "tuketici": ("tuketici", "ayipli", "garanti", "iade", "cayma", "mesafeli", "satici",
                 "abonelik", "hakem heyet"),
    "icra": ("icra", "haciz", "odeme emri", "ilamsiz", "senet", "borclu", "alacakli",
             "takip"),
    "trafik": ("trafik kaza", "deger kayb", "kasko", "zorunlu sigorta", "carpt",
               "ehliyet", "plaka", "pert"),
    "vergi": ("vergi", "kdv", "ozelge", "beyanname", "tarhiyat", "vergi ziyai", "gib",
              "mtv", "emlak vergi", "gelir vergi"),
    "tapu": ("tapu", "mulkiyet", "kat mulkiyet", "imar", "ortakligin giderilmes",
             "gecit hakk", "onalim", "parsel", "ifraz"),
    "idari": ("idari islem", "iptal davas", "kamulastir", "ruhsat", "disiplin cezas",
              "memur", "tam yargi", "yurutmeyi durdur", "zimni ret", "belediye"),
}


def _norm(text: str) -> str:
    """Türkçe-duyarsız normalize: küçült + aksanları sadeleştir (eşleşme için)."""
    lowered = text.casefold()
    # ç/ş/ğ/ı/ö/ü → c/s/g/i/o/u (işaretçiler ASCII tutuldu).
    decomposed = unicodedata.normalize("NFKD", lowered)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.replace("ı", "i").replace("ş", "s").replace("ğ", "g")


def is_out_of_scope(text: str) -> bool:
    """Metin ceza VEYA aile hukukuna mı ait? True → eğitim setinden ELE (kırmızı çizgi)."""
    norm = _norm(text)
    return any(marker in norm for marker in _OUT_OF_SCOPE_MARKERS)


def tag_domain(text: str) -> str:
    """En olası 8-sivil alan etiketi (best-effort); hiçbiri eşleşmezse 'genel'."""
    norm = _norm(text)
    best, best_hits = "genel", 0
    for domain, hints in _DOMAIN_HINTS.items():
        hits = sum(1 for h in hints if h in norm)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best


@dataclass(frozen=True, slots=True)
class QAPair:
    """(sorgu, pozitif belge) çifti — tripletin ilk iki ayağı."""

    query_id: str
    query: str
    pos_id: str
    pos_text: str
    domain: str
    source: str  # 'formal' (dataset query) | 'synth' (Qwen konuşma-dili)


# --- Konuşma-dili soru sentezi (InPars/Promptagator deseni; Qwen few-shot) ---

_SYNTH_SYSTEM = (
    "Sen Türkiye'de yaşayan SIRADAN bir vatandaşsın, hukukçu DEĞİLSİN. Sana bir hukuki "
    "metnin (kanun maddesi veya mahkeme kararı) konusu verilecek. Bu konunun anlattığı "
    "durumu BİZZAT yaşayan birinin, günlük konuşma diliyle soracağı TEK bir soru yaz. "
    "Kurallar: (1) Hukuk terimi/jargon kullanma, sade Türkçe. (2) Kanun adı, madde "
    "numarası veya karar numarası VERME. (3) Kendi başına geçmiş gibi, somut ve kısa "
    "yaz. (4) Sadece soruyu yaz, açıklama ekleme."
)

# Few-shot: (resmî konu → konuşma-dili vatandaş sorusu). SAHTE/örnek, gerçek kişi yok.
# Eş-anlam köprüsünü öğretir: 'mecur/güvence bedeli' → 'kiraladığım ev/depozito'.
_SYNTH_FEWSHOT: tuple[tuple[str, str], ...] = (
    (
        "Borçlar Hukuku – Konut kira sözleşmesinin kiracı tarafından süresinden önce "
        "feshi – mecurun erken tahliyesi – güvence bedelinin iadesi",
        "Kiraladığım evden kontrat bitmeden çıktım, ev sahibi depozitomu geri vermiyor, "
        "ne yapabilirim?",
    ),
    (
        "İş Hukuku – haklı neden olmaksızın iş akdinin işveren tarafından feshi – kıdem "
        "ve ihbar tazminatı – fazla çalışma ücreti",
        "5 yıldır çalıştığım işten sebepsiz çıkardılar, tazminatımı ve fazla mesai "
        "paramı alabilir miyim?",
    ),
    (
        "Tüketici Hukuku – ayıplı mal – satıcının sorumluluğu – ücretsiz onarım veya "
        "ayıpsız misli ile değişim talebi",
        "İnternetten aldığım telefon bozuk çıktı, satıcı değiştirmiyor, hakkım ne?",
    ),
)


def build_synth_messages(pos_text: str, *, topic_chars: int = 600) -> list[dict[str, str]]:
    """Konuşma-dili soru üretimi için few-shot mesaj listesi (LLM.chat girdisi).

    Pozitif belgenin BAŞINI konu olarak verir (tam metin değil — token tasarrufu +
    LLM'in konuya odaklanması). Saf: yalnız mesajları kurar, LLM çağırmaz.
    """
    topic = " ".join(pos_text.split())[:topic_chars]
    messages: list[dict[str, str]] = [{"role": "system", "content": _SYNTH_SYSTEM}]
    for formal, colloquial in _SYNTH_FEWSHOT:
        messages.append({"role": "user", "content": f"Konu: {formal}"})
        messages.append({"role": "assistant", "content": colloquial})
    messages.append({"role": "user", "content": f"Konu: {topic}"})
    return messages


_MADDE_NO_RE = re.compile(r"\bmadde\s*\d+|\bm\.\s*\d+|\d+\s*sayılı", re.IGNORECASE)
_QUOTE_STRIP_RE = re.compile(r'^["\'`“”]+|["\'`“”]+$')


def _token_set(text: str) -> set[str]:
    return {t for t in re.split(r"\W+", _norm(text)) if len(t) > 2}


def clean_synth_query(raw: str, pos_text: str, *, min_len: int = 15,
                      max_len: int = 300, max_overlap: float = 0.8) -> str | None:
    """Sentezlenen ham çıktıyı doğrula/temizle → geçerli soru veya None (AT).

    Reddeder: boş / çok kısa-uzun / madde-no içeren (jargon) / belgeyi kopyalamış
    (yüksek token örtüşmesi). None dönerse çağıran bu örneği atar.
    """
    if not raw:
        return None
    # İlk satır + tırnak kırp (LLM bazen açıklama/tırnak ekler).
    q = _QUOTE_STRIP_RE.sub("", raw.strip().splitlines()[0].strip()) if raw.strip() else ""
    if not (min_len <= len(q) <= max_len):
        return None
    if _MADDE_NO_RE.search(q):
        return None  # jargon/atıf — konuşma-dili değil
    # Belgeyi kopyalamış mı? (sentez sorgu token'larının çoğu belgedeyse AT)
    q_tokens = _token_set(q)
    if not q_tokens:
        return None
    overlap = len(q_tokens & _token_set(pos_text)) / len(q_tokens)
    if overlap > max_overlap:
        return None
    return q


def roundtrip_keep(source_pos_id: str, retrieved_ids: list[str], *, top_k: int = 10) -> bool:
    """Round-trip filtre: sentez sorgu KENDİ kaynağını geri getiriyor mu?

    Mevcut retriever sentez soruyla kaynak belgeyi top_k'da bulabiliyorsa, soru
    'aranabilir' demektir → TUT. Bulamıyorsa muğlak/alakasız → AT. Eş-anlam
    köprüsünün gerçekten kurulduğunu garanti eder (depozito→güvence bedeli).
    """
    return source_pos_id in set(retrieved_ids[:top_k])


# --- Triplet/çift şekillendirme + split ---

def dedup_pairs(pairs: list[QAPair]) -> list[QAPair]:
    """(query, pos_id) çiftine göre dedup — sıra korunur (ilk görülen kalır)."""
    seen: set[tuple[str, str]] = set()
    out: list[QAPair] = []
    for p in pairs:
        key = (_norm(p.query), p.pos_id)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def labeled_pairs_from_mined(query: str, pos_text: str,
                             negatives: list[str]) -> list[dict]:
    """Bir (sorgu, pozitif, [negatifler]) → CrossEncoder etiketli-çift kayıtları.

    Pozitif → label 1.0, her negatif → label 0.0. CrossEncoder BinaryCrossEntropyLoss
    girdisi (query/passage/label). Negatif yoksa yalnız pozitif döner.
    """
    rows = [{"query": query, "passage": pos_text, "label": 1.0}]
    rows.extend({"query": query, "passage": neg, "label": 0.0} for neg in negatives)
    return rows


def split_train_val(rows: list, val_frac: float = 0.1, seed: int = 42) -> tuple[list, list]:
    """Deterministik train/val ayrımı (seed'li shuffle). val en az 1 satır."""
    if not rows:
        return [], []
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    n_val = max(1, int(len(shuffled) * val_frac))
    return shuffled[n_val:], shuffled[:n_val]
