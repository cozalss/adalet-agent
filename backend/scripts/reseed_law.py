"""Tek bir kanunu yeniden seed et — eksik/kısmi seed onarımı.

`seed_mevzuat.py` tüm kanunları çeker; bu script SADECE verilen kanun kodlarını
yeniden çekip Qdrant'a yazar. Madde id'leri deterministik (`m-<KOD>-<madde>`)
olduğundan upsert idempotent: mevcut maddeler güncellenir, eksik maddeler
(örn. TKHK m.11 ayıplı mal seçimlik hakları) eklenir, duplicate olmaz.

Neden gerekli: corpus eski/eksik bir seed ile yazılmıştı (örn. TKHK'da ayıplı
mal çekirdek maddeleri m.9/11/12 yoktu → tüketici sorguları doğru kaynağı
bulamıyordu). Mevcut fetch+chunker bu maddeleri doğru üretiyor.

Çalıştırma:
    uv run python -m scripts.reseed_law TKHK
    uv run python -m scripts.reseed_law TKHK IK TBK
"""

from __future__ import annotations

import asyncio
import logging
import sys

from core import native_preload  # noqa: F401  pyarrow'u torch'tan önce yükle
from retrieval.embedding import Embedder
from retrieval.mevzuat_client import KANUN_KODU_TO_NUMARA, MevzuatClient
from retrieval.vector_store import ensure_collection, get_client
from scripts.seed_mevzuat import TARGET_LAWS, _seed_one_law

logger = logging.getLogger("scripts.reseed_law")

_KODU_TO_ADI = dict(TARGET_LAWS)


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    kodlar = [a.strip().upper() for a in sys.argv[1:] if a.strip()]
    if not kodlar:
        print("Kullanım: uv run python -m scripts.reseed_law <KANUN_KODU> [<KOD>...]")
        print("Örn: uv run python -m scripts.reseed_law TKHK")
        return 2

    unknown = [k for k in kodlar if k not in KANUN_KODU_TO_NUMARA]
    if unknown:
        print(f"Bilinmeyen kanun kodu: {unknown}")
        return 2

    logger.info("reseed_started laws=%s", kodlar)
    embedder = Embedder()
    _ = embedder.encode(["sıcak başlatma"], batch_size=1)
    logger.info("embedder_ready")

    qdrant = get_client()
    try:
        await ensure_collection(qdrant)
        async with MevzuatClient() as mevzuat_client:
            total = 0
            for kodu in kodlar:
                adi = _KODU_TO_ADI.get(kodu, kodu)
                try:
                    count = await _seed_one_law(
                        mevzuat_client, embedder, qdrant, kodu, adi,
                    )
                    total += count
                    logger.info("reseed_done %s madde=%d", kodu, count)
                except Exception as exc:
                    logger.exception("reseed_failed %s: %s", kodu, exc)
        logger.info("=" * 50)
        logger.info("RESEED TOPLAM: %d madde", total)
    finally:
        await qdrant.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
