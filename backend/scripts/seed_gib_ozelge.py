"""GİB özelge seed — vergi domain için resmi tax rulings (18k+ kayıt).

Vergi domain'i corpus'ta hafif; GİB özelge yargi-mcp'de search_gib_ozelge ile
relevance-ranked erişilebilir. domain="vergi", source="gib_ozelge".

Kullanım:
    uv run python -m scripts.seed_gib_ozelge --limit 200
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

# Windows: pyarrow'u torch'tan önce yükle (BGE-M3 warmup segfault fix).
from core import native_preload  # noqa: F401
from retrieval.chunker import chunk_decision
from retrieval.embedding import Embedder
from retrieval.vector_store import ChunkPoint, ensure_collection, get_client, upsert_chunks
from retrieval.yargi_client import YargiClient

logger = logging.getLogger("scripts.seed_gib_ozelge")

VERGI_KEYWORDS: tuple[str, ...] = (
    # Ana vergi türleri — broad
    "katma değer vergisi",
    "kurumlar vergisi",
    "gelir vergisi",
    "özel tüketim vergisi",
    "damga vergisi",
    "motorlu taşıt vergisi",
    "emlak vergisi",
    "veraset intikal vergisi",
    # İşlem-bazlı kavramlar — farklı topic
    "stopaj",
    "ihracat istisnası",
    "kanunen kabul edilmeyen gider",
    "transfer fiyatlandırması",
    "indirim",
    "iade",
    "muhtasar beyan",
    "sahte fatura",
    "vergi ziyaı",
    "vergi inceleme",
)

# Vergi kanunları — kanun_no filtresiyle her kanunun ayrı ozelge seti
# çekilir; keyword overlap dedup problemi yok. Per-kanun limit ortalamasıyla
# total yield çok daha fazla. (numara → kısa açıklama).
VERGI_KANUN_NOS: tuple[tuple[str, str], ...] = (
    ("3065", "KDV"),
    ("193",  "Gelir Vergisi"),
    ("5520", "Kurumlar Vergisi"),
    ("213",  "Vergi Usul Kanunu"),
    ("4760", "Özel Tüketim Vergisi"),
    ("488",  "Damga Vergisi"),
    ("197",  "Motorlu Taşıt Vergisi"),
    ("1319", "Emlak Vergisi"),
    ("7338", "Veraset İntikal Vergisi"),
    ("6183", "Amme Alacakları"),
)


async def _run(args: argparse.Namespace) -> int:
    logger.info("seed_started domain=vergi limit=%d", args.limit)
    embedder = Embedder()
    _ = embedder.encode(["sıcak başlatma"], batch_size=1)
    logger.info("embedder_ready")

    qdrant = get_client()
    seen_ids: set[str] = set()
    pending: list[tuple[str, str, dict]] = []
    n_docs = n_chunks = 0

    async def _flush() -> None:
        nonlocal n_chunks
        if not pending:
            return
        texts = [t for t, _, _ in pending]
        out = await asyncio.to_thread(embedder.encode, texts, 8)
        points = [
            ChunkPoint(
                id=cid, dense_vector=dense,
                sparse_indices=sparse[0], sparse_values=sparse[1],
                payload=payload,
            )
            for (_, cid, payload), dense, sparse in zip(pending, out.dense, out.sparse)
        ]
        await upsert_chunks(qdrant, points)
        n_chunks += len(points)
        pending.clear()

    async def _consume(decs, label: str) -> int:
        """Bir search call sonucunu işle: dedup + fetch + chunk + buffer. Yeni doc sayısı."""
        nonlocal n_docs
        new = 0
        for dec in decs:
            if n_docs >= args.limit:
                break
            oid = dec.decision_id
            if not oid or oid in seen_ids:
                continue
            seen_ids.add(oid)
            try:
                text = await client.get_regulator_document("gib_ozelge", oid)
            except Exception as exc:
                logger.warning("fetch_failed id=%s err=%s", oid, str(exc)[:120])
                continue
            if not text or len(text) < 200:
                continue
            chunks = chunk_decision(text)
            if not chunks:
                continue
            raw = dec.raw or {}
            base = {
                "doc_id": f"o-{oid}",
                "court": "gib",
                "chamber": raw.get("kanunTitle"),
                "date": dec.date,
                "title": (dec.title or "") + (
                    f" (özelge {raw.get('ozelgeNo','')})" if raw.get("ozelgeNo") else ""
                ),
                "source": "gib_ozelge",
                "source_url": dec.source_url,
                "domain": "vergi",
                "doc_type": "case",
                "ozelge_no": raw.get("ozelgeNo"),
                "kanun_no": raw.get("kanunNo"),
            }
            for seq, c in enumerate(chunks):
                cid = f"o-{oid}-c{seq}"
                payload = {**base, "chunk_id": cid, "chunk_seq": seq,
                           "text": c.text, "section": c.metadata.get("section", "gerekce")}
                pending.append((c.text, cid, payload))
            n_docs += 1
            new += 1
            if len(pending) >= args.batch_chunks:
                await _flush()
            if n_docs % 20 == 0:
                logger.info("progress n_docs=%d (%s)", n_docs, label)
        return new

    try:
        await ensure_collection(qdrant)
        async with YargiClient() as client:
            # 1) Per-kanun_no iterasyon — her vergi kanunu ayrı ozelge seti veriyor,
            # keyword-overlap dedup darboğazı olmaksızın yüksek yield. Bu, broad
            # keyword'ün 142'de takıldığı yerde 1000+ chunk açar.
            for kno, kadi in VERGI_KANUN_NOS:
                if n_docs >= args.limit:
                    break
                logger.info("kanun_started no=%s ad=%s", kno, kadi)
                page = 1
                while n_docs < args.limit:
                    try:
                        decs = await client.search_gib_ozelge(kanun_no=kno, page=page, page_size=20)
                    except Exception as exc:
                        logger.warning("search_failed kanun=%s page=%d err=%s", kno, page, str(exc)[:120])
                        break
                    if not decs:
                        break
                    new = await _consume(decs, f"kanun={kadi}")
                    if new == 0:
                        break
                    page += 1
            # 2) Keyword bazlı tarama (kanun_no'ya bağlı olmayan transactional
            # kavramlar: stopaj, ihracat istisnası, transfer fiyat., vs.)
            for kw in VERGI_KEYWORDS:
                if n_docs >= args.limit:
                    break
                page = 1
                while n_docs < args.limit:
                    try:
                        decs = await client.search_gib_ozelge(keywords=kw, page=page, page_size=20)
                    except Exception as exc:
                        logger.warning("search_failed kw=%s page=%d err=%s", kw, page, str(exc)[:120])
                        break
                    if not decs:
                        break
                    new = await _consume(decs, f"kw={kw}")
                    if new == 0:
                        break
                    page += 1
            await _flush()
        logger.info("=" * 50)
        logger.info("GIB OZELGE SEED TOPLAM: %d kayit, %d chunk (domain=vergi)", n_docs, n_chunks)
    finally:
        await qdrant.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.seed_gib_ozelge")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--batch-chunks", type=int, default=100)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
