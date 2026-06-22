"""Firecrawl ile mevzuat.gov.tr'den KANUN/YÖNETMELİK çek → chunk → embed → Qdrant (korpus zenginleştirme).

Mevcut seed_mevzuat pipeline'ını YENİDEN KULLANIR (chunk_mevzuat / Embedder / upsert_chunks /
_build_maddeler); tek fark FETCH kaynağı: mevzuat-mcp yerine FIRECRAWL (daha geniş kapsam —
mevzuat-mcp listesinde olmayan kanun/yönetmelikleri de ekler).

Firecrawl markdown'ı madde başlıklarını **bold** verir (`**MADDE 17-**`); `extract_law_body`
bold'u sıyırıp nav/logo/link'i temizler → chunk_mevzuat "MADDE N-" parse'ı çalışır (deney: KVKK
51K markdown → 36 MADDE temiz). Madde.id DETERMİNİSTİK (m-KVKK-1) → idempotent (tekrar = overwrite).

Kullanım:
    LLM_MODE=mock uv run python -m scripts.seed_firecrawl_mevzuat            # tüm LAWS
    LLM_MODE=mock uv run python -m scripts.seed_firecrawl_mevzuat --limit 5  # ilk 5
    ... --only KVKK,SermayePiyasasi                                          # seçili

SADECE resmi mevzuat.gov.tr (firecrawl_client allowlist). Sıfır halüsinasyon: içerik resmi sayfadan.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path

# .env yükle (EMBEDDING_MODEL/QDRANT_COLLECTION/FIRECRAWL_API_KEY) — retrieval import'larından ÖNCE,
# yoksa yanlış collection/embedder kullanılır. override=False: dış env öncelikli.
_ENV = Path(".env")
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from core import native_preload  # noqa: F401  (pyarrow↔torch sırası — Windows)
from retrieval.chunker import sanitize_text
from retrieval.embedding import Embedder
from retrieval.firecrawl_client import scrape_legal_url
from retrieval.vector_store import ChunkPoint, ensure_collection, get_client, upsert_chunks
from scripts.seed_mevzuat import _build_maddeler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("seed_firecrawl")

# Korpusu zenginleştirecek kanun/yönetmelikler. (kodu, numara, adi, MevzuatNo, Tur, Tertip)
# Tur: 1=Kanun, 7=Yönetmelik. Listeyi genişlet → daha çok kaynak. mevzuat.gov.tr arama URL'i.
# ÖNEMLİ: `kodu` agents/config.py DOMAIN_TO_KANUN_KODU'daki KANONİK kodla EŞLEŞMELİ — yoksa chunk
# domain-boost almaz (içerikçe yine retrievable ama tier-2). Yeni bir KOD eklersen onu da
# DOMAIN_TO_KANUN_KODU'ya kaydet. Aşağıdakiler zaten kürate listede (refresh + tazeleme).
# GERÇEK "daha çok kaynak" için: (a) YÖNETMELİKLER (korpusta ~128, büyük boşluk; Tur=7), veya
# (b) yeni domain (kapsam genişletme). Kanunlar 8 domainde çoğunlukla mevcut.
LAWS: list[dict] = [
    {"kodu": "ISGK", "numara": "6331", "adi": "İş Sağlığı ve Güvenliği Kanunu", "no": "6331", "tur": 1, "tertip": 5},
    {"kodu": "SK", "numara": "6356", "adi": "Sendikalar ve Toplu İş Sözleşmesi Kanunu", "no": "6356", "tur": 1, "tertip": 5},
    {"kodu": "KMK", "numara": "634", "adi": "Kat Mülkiyeti Kanunu", "no": "634", "tur": 1, "tertip": 3},
    {"kodu": "TPK", "numara": "2644", "adi": "Tapu Kanunu", "no": "2644", "tur": 1, "tertip": 3},
    {"kodu": "IMARK", "numara": "3194", "adi": "İmar Kanunu", "no": "3194", "tur": 1, "tertip": 5},
    {"kodu": "IYUK", "numara": "2577", "adi": "İdari Yargılama Usulü Kanunu", "no": "2577", "tur": 1, "tertip": 5},
    {"kodu": "IHK", "numara": "4734", "adi": "Kamu İhale Kanunu", "no": "4734", "tur": 1, "tertip": 5},
    {"kodu": "KTK", "numara": "2918", "adi": "Karayolları Trafik Kanunu", "no": "2918", "tur": 1, "tertip": 5},
    {"kodu": "KDV", "numara": "3065", "adi": "Katma Değer Vergisi Kanunu", "no": "3065", "tur": 1, "tertip": 5},
    {"kodu": "DV", "numara": "488", "adi": "Damga Vergisi Kanunu", "no": "488", "tur": 1, "tertip": 3},
]


def _mevzuat_url(law: dict) -> str:
    return (
        f"https://www.mevzuat.gov.tr/mevzuat?MevzuatNo={law['no']}"
        f"&MevzuatTur={law['tur']}&MevzuatTertip={law['tertip']}"
    )


def extract_law_body(md: str) -> str:
    """Firecrawl mevzuat markdown'ından kanun gövdesini çıkar (bold-sıyır + nav/link temizle)."""
    body = re.sub(r"\*\*([^*]+)\*\*", r"\1", md or "")        # **MADDE 17-** → MADDE 17-
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)          # görseller
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)      # linkler → metin
    m = re.search(r"(?m)^\s*MADDE\s+1\b", body) or re.search(r"MADDE\s+1\b", body)
    if m:
        body = body[m.start():]
    return sanitize_text(body)


async def seed_one(law: dict, embedder: Embedder, qdrant) -> int:
    """Tek kanunu Firecrawl'la çek → temizle → chunk → embed → upsert. Madde sayısı döndürür."""
    url = _mevzuat_url(law)
    logger.info("scrape %s (%s)...", law["kodu"], law["numara"])
    md = await scrape_legal_url(url, timeout_s=70)
    if not md:
        logger.warning("scrape_empty %s — atlandı (Firecrawl boş)", law["kodu"])
        return 0
    body = extract_law_body(md)
    maddeler = _build_maddeler(law["kodu"], law["numara"], law["adi"], body, "")
    if not maddeler:
        logger.warning("no_maddeler %s (markdown=%d body=%d) — atlandı", law["kodu"], len(md), len(body))
        return 0

    texts = [m.metin for m in maddeler]
    out = await asyncio.to_thread(embedder.encode, texts, 8)
    points = [
        ChunkPoint(
            id=m.id,
            dense_vector=dense,
            sparse_indices=sparse[0],
            sparse_values=sparse[1],
            payload={**m.to_payload(), "text": m.metin},
        )
        for m, dense, sparse in zip(maddeler, out.dense, out.sparse)
    ]
    await upsert_chunks(qdrant, points)
    logger.info("✓ upserted %s madde=%d", law["kodu"], len(points))
    return len(points)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="ilk N kanun (0=hepsi)")
    ap.add_argument("--only", type=str, default="", help="virgüllü kodlar (örn KVKK,TTK)")
    args = ap.parse_args()

    laws = LAWS
    if args.only:
        want = {x.strip() for x in args.only.split(",")}
        laws = [law for law in laws if law["kodu"] in want]
    if args.limit > 0:
        laws = laws[: args.limit]

    logger.info("warming_embedder...")
    embedder = Embedder()
    qdrant = get_client()
    await ensure_collection(qdrant)

    total = 0
    ok = 0
    for law in laws:
        try:
            n = await seed_one(law, embedder, qdrant)
            total += n
            ok += 1 if n else 0
        except Exception as exc:  # tek kanun hatası tüm batch'i bozmasın
            logger.warning("law_failed %s: %s", law["kodu"], type(exc).__name__)
    logger.info("=== BİTTİ: %d/%d kanun, toplam %d madde upserted ===", ok, len(laws), total)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
