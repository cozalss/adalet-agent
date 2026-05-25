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

MADDE_PATTERN = re.compile(
    r"(?=(?:^|\n)\s*Madde\s+\d+[\.\-—\s])",
    re.IGNORECASE | re.MULTILINE,
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


def chunk_mevzuat(text: str) -> list[Chunk]:
    """Mevzuat metnini madde başlıklarına göre böl.

    "Madde 11 — ..." gibi başlıklar ayrı chunk olur. Madde numarası metadata'ya
    yazılır → citation verification'da hızlı arama için.
    """
    text = text.strip()
    if not text:
        return []

    parts = MADDE_PATTERN.split(text)
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return [Chunk(text=text, seq=0, metadata={})]

    chunks: list[Chunk] = []
    for seq, part in enumerate(parts):
        madde_match = re.match(r"Madde\s+(\d+)", part, re.IGNORECASE)
        metadata = {"madde_no": int(madde_match.group(1))} if madde_match else {}
        chunks.append(Chunk(text=part, seq=seq, metadata=metadata))

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
