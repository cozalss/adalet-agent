"""Metin chunk'lama — uzun belgeleri retrieval için bölümlere ayır.

Strateji:
- Önce paragraf bazında ayır (\n\n)
- Sonra her chunk için karakter limiti uygula
- Chunk'lar arasında overlap → bağlam kaybını azalt
- Mevzuat maddeleri için "Madde X" başlıklarını ayrı chunk olarak tut
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass

# Ek/Geçici madde desteği (P8, 2026-06-11): 'EK MADDE 11' / 'Geçici Madde 2' başlıkları
# split'i tetiklemiyordu → metinleri önceki numaralı maddenin chunk'ına yapışıyordu
# (ölçüldü: 283 chunk YANLIŞ madde_no altında ek/geçici metni taşıyor = kontaminasyon,
# sıfır-halüsinasyon riski). DİKKAT: Türkçe 'İ' re.IGNORECASE ile eşleşMEZ ('İ'.lower()
# = 'i̇' iki karakter) → 'GEÇİCİ' için açık alternation şart.
_EK_PREFIX = r"(?:EK|Ek|ek)"
_GECICI_PREFIX = r"(?:GEÇİCİ|Geçici|geçici)"
_MADDE_TUR_PREFIX = rf"(?:{_EK_PREFIX}\s+|{_GECICI_PREFIX}\s+)?"

MADDE_PATTERN = re.compile(
    rf"(?=(?:^|\n)\s*{_MADDE_TUR_PREFIX}Madde\s+\d+[\.\-—\s])",
    re.IGNORECASE | re.MULTILINE,
)

# Chunk başındaki madde başlığı: (madde_tur, madde_no) çıkarımı.
_MADDE_HEADER_RE = re.compile(
    rf"(?:(?P<ek>{_EK_PREFIX})\s+|(?P<gecici>{_GECICI_PREFIX})\s+)?Madde\s+(?P<no>\d+)",
    re.IGNORECASE,
)

# Latin-1-in-UTF-8 Mojibake: PDF/Word kaynaklı kararlarda sık görülür.
_MOJIBAKE_FIXES = (
    ("Ã§", "ç"), ("Ã‡", "Ç"),
    ("ÄŸ", "ğ"), ("Äž", "Ğ"),
    ("Ä±", "ı"), ("Ä°", "İ"),
    ("Ã¶", "ö"), ("Ã–", "Ö"),
    ("ÅŸ", "ş"), ("Åž", "Ş"),
    ("Ã¼", "ü"), ("Ãœ", "Ü"),
    ("â€™", "'"), ("â€œ", "\""), ("â€", "\""),
    ("â€“", "–"), ("â€”", "—"),
    ("Â ", " "),  # nbsp double-encoded
    (" ", " "),  # nbsp → space
)


def sanitize_text(text: str) -> str:
    """Mojibake + control char temizliği — Türk hukuk kararlarındaki encoding sorunları."""
    if not text:
        return text
    for bad, good in _MOJIBAKE_FIXES:
        if bad in text:
            text = text.replace(bad, good)
    # Unicode normalize NFC (Türkçe karakterler için tutarlı kompozisyon)
    text = unicodedata.normalize("NFC", text)
    # Control char strip (line break + tab hariç)
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t ")
    return text


@dataclass(slots=True)
class Chunk:
    text: str
    seq: int
    metadata: dict


def chunk_text(
    text: str,
    chunk_chars: int = 1200,
    overlap_chars: int = 200,
    min_chars: int = 80,
) -> list[str]:
    """Karakter bazlı sliding window — paragraf sınırlarını korumaya çalışır."""
    text = sanitize_text(text).strip()
    if not text or len(text) < min_chars:
        return []

    if len(text) <= chunk_chars:
        return [text]

    chunks: list[str] = []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    buffer = ""

    for para in paragraphs:
        if len(buffer) + len(para) + 2 <= chunk_chars:
            buffer = f"{buffer}\n\n{para}" if buffer else para
            continue

        if buffer:
            chunks.append(buffer)
        if len(para) > chunk_chars:
            chunks.extend(_split_oversize(para, chunk_chars, overlap_chars))
            buffer = ""
        else:
            buffer = para

    if buffer:
        chunks.append(buffer)

    # min_chars filtre _split_oversize çıktısı için de çalışır — küçük tail'leri at
    cleaned = [c for c in chunks if len(c.strip()) >= min_chars]
    return _apply_overlap(cleaned, overlap_chars)


# Bu boyutu (char) aşan madde çok-fıkralı sayılır → paragraf-aware alt-bölünür. Tek dev
# chunk'ta dense embedding tüm madde üzerinde ortalanır, spesifik fıkra ('VUK 359/b')
# sinyali dilüe olur (özellikle Mursit dense-only prod default'ta). Denetim 2026-06-04.
_MEVZUAT_SUBCHUNK_THRESHOLD = 1500


def chunk_mevzuat(text: str, *, subchunk: bool = True) -> list[Chunk]:
    """Mevzuat metnini madde başlıklarına göre böl.

    "Madde 11 — ..." gibi başlıklar ayrı chunk olur. Madde numarası metadata'ya
    yazılır → citation verification'da hızlı arama için. Çok-fıkralı UZUN maddeler
    (> _MEVZUAT_SUBCHUNK_THRESHOLD) paragraf-aware alt-chunk'lara bölünür; her alt-chunk
    AYNI madde_no'yu taşır → citation/fetch_maddeler bozulmaz, yalnız madde başına >1 chunk.

    subchunk=False (P8 reseed dersi, 2026-06-11): SEED yolu madde başına TEK tam-metin
    chunk ister — Madde.id madde-bazlı olduğundan alt-chunk'lar upsert'te çakışıp yalnız
    SON (kuyruk) parça hayatta kalıyordu → maddenin başı (başlık+ilk fıkralar) corpus'tan
    siliniyordu (VUK-359 kelime ortasından başlar bulundu; dev madde@8 69.8→62.6
    regresyonunun kök nedeni). Eski corpus alt-chunk özelliğinden önce seed edilmişti.
    """
    text = text.strip()
    if not text:
        return []

    parts = MADDE_PATTERN.split(text)
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return [Chunk(text=text, seq=0, metadata={})]

    chunks: list[Chunk] = []
    seq = 0
    for part in parts:
        madde_match = _MADDE_HEADER_RE.match(part)
        if madde_match:
            tur = ("ek" if madde_match.group("ek")
                   else "gecici" if madde_match.group("gecici") else "madde")
            metadata = {"madde_no": int(madde_match.group("no")), "madde_tur": tur}
        else:
            metadata = {}
        if subchunk and len(part) > _MEVZUAT_SUBCHUNK_THRESHOLD:
            # Uzun madde → paragraf/fıkra-aware alt-böl (overlap ile bağlam korunur).
            for sub in chunk_text(part, chunk_chars=1000, overlap_chars=150) or [part]:
                chunks.append(Chunk(text=sub, seq=seq, metadata=dict(metadata)))
                seq += 1
        else:
            chunks.append(Chunk(text=part, seq=seq, metadata=metadata))
            seq += 1

    return chunks


# Sprint-5 W14.7: Yargıtay/Danıştay karar metni section markers.
# Bedesten output'ları genelde başlıkları içerir (gerekçe, hüküm/sonuç) —
# bu marker'ları yakalayıp chunk metadata'sına "section" ekleriz. Retrieval
# kalitesi artar: "tazminat miktarı nasıl hesaplanır" sorgusu gerekçe section'a
# daha çok yakın gelir, "karar verildi mi" sorgusu hüküm section'a.
#
# Anchor: marker satır başında (`^`) olmalı + iki nokta (`:`) ZORUNLU.
# Bu kombinasyon "Davacı" gibi paragraf içi geçişlerin yanlış match'ini engeller.
_DECISION_SECTION_RE = re.compile(
    r"^[ \t]*(?P<header>"
    r"DAVA(?:NIN)?|"
    r"OLAY(?:LAR)?|"
    r"İSTEM|"
    r"GEREKÇE|"
    r"HUKUKİ\s+DEĞERLENDİRME|"
    r"DEĞERLENDİRME|"
    r"HÜKÜM|"
    r"SONUÇ|"
    r"KARAR"
    r")[ \t]*:",
    re.IGNORECASE | re.MULTILINE,
)


def _classify_section(header: str) -> str:
    """Section başlığını standart kategoriye eşle: olay/gerekce/sonuc."""
    h = header.upper().strip().rstrip(":").strip()
    if h in {"DAVA", "DAVANIN", "OLAY", "OLAYLAR", "İSTEM"}:
        return "olay"
    if h in {"GEREKÇE", "HUKUKİ DEĞERLENDİRME", "DEĞERLENDİRME"}:
        return "gerekce"
    if h in {"HÜKÜM", "SONUÇ", "KARAR"}:
        return "sonuc"
    return "gerekce"  # Varsayılan: bilinmeyen header → gerekçe sayılır


def chunk_decision(
    text: str,
    chunk_chars: int = 1200,
    overlap_chars: int = 200,
    min_chars: int = 80,
) -> list[Chunk]:
    """Yargıtay/Danıştay karar metnini gerekçe/sonuç ayrımı ile chunk'la.

    Section marker bulunamazsa `chunk_text` fallback'i — flat chunk list dönülür,
    section metadata "gerekce" (default) olur.

    Section bulunduğunda her section ayrı ayrı sliding-window'a sokulur ve
    sonuç chunk'ların metadata'sına "section" eklenir.
    """
    text = sanitize_text(text).strip()
    if not text:
        return []

    # Section başlıklarını yakala
    matches = list(_DECISION_SECTION_RE.finditer(text))
    if not matches:
        # Marker yok — flat chunk list, default section "gerekce"
        return [
            Chunk(text=ch, seq=i, metadata={"section": "gerekce"})
            for i, ch in enumerate(chunk_text(text, chunk_chars, overlap_chars, min_chars))
        ]

    # Section'lara böl: her match start'ından bir sonrakine
    chunks: list[Chunk] = []
    seq = 0
    for i, m in enumerate(matches):
        section = _classify_section(m.group("header"))
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if not body or len(body) < min_chars:
            continue
        for chunk_body in chunk_text(body, chunk_chars, overlap_chars, min_chars):
            chunks.append(
                Chunk(text=chunk_body, seq=seq, metadata={"section": section})
            )
            seq += 1

    if not chunks:
        # Section başlıkları vardı ama hepsi çok kısa — fallback
        return [
            Chunk(text=ch, seq=i, metadata={"section": "gerekce"})
            for i, ch in enumerate(chunk_text(text, chunk_chars, overlap_chars, min_chars))
        ]
    return chunks


def _split_oversize(text: str, chunk_chars: int, overlap_chars: int) -> list[str]:
    """Tek bir paragraf chunk_chars'tan büyükse cümle/karakter bazlı böl."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    buffer = ""

    for sentence in sentences:
        if len(buffer) + len(sentence) + 1 <= chunk_chars:
            buffer = f"{buffer} {sentence}".strip()
            continue

        if buffer:
            chunks.append(buffer)
        if len(sentence) > chunk_chars:
            for start in range(0, len(sentence), chunk_chars - overlap_chars):
                chunks.append(sentence[start : start + chunk_chars])
            buffer = ""
        else:
            buffer = sentence

    if buffer:
        chunks.append(buffer)
    return chunks


def _apply_overlap(chunks: list[str], overlap_chars: int) -> list[str]:
    """Komşu chunk'lar arasına önceki chunk'ın son N karakterini ekle."""
    if overlap_chars <= 0 or len(chunks) <= 1:
        return chunks

    overlapped: list[str] = [chunks[0]]
    for prev, curr in itertools.pairwise(chunks):
        tail = prev[-overlap_chars:]
        overlapped.append(f"{tail}\n\n{curr}" if not curr.startswith(tail) else curr)
    return overlapped
