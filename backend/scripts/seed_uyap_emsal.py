"""UYAP emsal seed — özel hukuk domainleri için keyword-relevance kararları.

Public Bedesten phrase-search'in aksine UYAP gerçek keyword eşleşmesi yapar:
"ayıplı mal tüketici" sorgusu için Bölge Adliye Mahkemesi + Asliye Ticaret/Hukuk
kararlarını döndürür. tools/list keşfinden sonra eklendi (yargi_client.search_emsal).

Kullanım:
    uv run python -m scripts.seed_uyap_emsal --domain tuketici --limit 60
    uv run python -m scripts.seed_uyap_emsal --domain isHukuku --limit 60
    uv run python -m scripts.seed_uyap_emsal --domain kira --limit 60
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
from retrieval.yargi_client import YargiClient, YargitayDecision

logger = logging.getLogger("scripts.seed_uyap_emsal")

# Domain başına UYAP keyword listesi. UYAP keyword-match yaptığı için broad'
# keywordler genelde daha fazla relevant sonuç döndürür; ek per-domain content
# filtresine ihtiyaç yok — istinaf prosedürel kararları bile en azından konuya
# referans veriyor (cross-encoder retrieval'da gerçek alakayı sıralar).
DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "tuketici": (
        "tüketici", "ayıplı mal", "ayıplı araç", "garanti süresi",
        "tüketici hakem heyeti", "mesafeli sözleşme", "tüketici kredisi",
    ),
    "isHukuku": (
        "kıdem tazminatı", "ihbar tazminatı", "işçi alacağı", "haksız fesih",
        "fazla mesai", "iş kazası", "işe iade", "yıllık izin",
    ),
    "kira": (
        "kira sözleşmesi", "tahliye", "kira artış", "depozito",
        "iki haklı ihtar", "kira uyarlama", "ecrimisil",
    ),
    "trafik": (
        "trafik kazası", "maddi tazminat", "manevi tazminat",
        "destekten yoksun kalma", "kasko sigortası", "ZMSS",
        "kusur oranı", "değer kaybı",
    ),
    "tapu": (
        "tapu iptali", "tapu tescili", "kamulaştırma",
        "müdahalenin men'i", "ecrimisil", "ortaklığın giderilmesi",
        "izale-i şuyu", "muris muvazaası",
    ),
}


async def _seed_domain(
    client: YargiClient,
    embedder: Embedder,
    qdrant,
    domain: str,
    limit: int,
    batch_chunks: int,
) -> tuple[int, int]:
    """Tek bir domain için UYAP emsal seed. Döndürdüğü: (docs, chunks)."""
    keywords = DOMAIN_KEYWORDS[domain]
    seen_ids: set[str] = set()
    pending_chunks: list[tuple[str, str, dict]] = []  # (chunk_text, chunk_id, payload)
    n_docs = n_chunks = 0

    async def _flush() -> None:
        nonlocal n_chunks
        if not pending_chunks:
            return
        texts = [t for t, _, _ in pending_chunks]
        out = await asyncio.to_thread(embedder.encode, texts, 8)
        points = [
            ChunkPoint(
                id=cid, dense_vector=dense,
                sparse_indices=sparse[0], sparse_values=sparse[1],
                payload=payload,
            )
            for (_, cid, payload), dense, sparse in zip(pending_chunks, out.dense, out.sparse)
        ]
        await upsert_chunks(qdrant, points)
        n_chunks += len(points)
        pending_chunks.clear()

    for kw in keywords:
        if n_docs >= limit:
            break
        page = 1
        while n_docs < limit:
            try:
                decs: list[YargitayDecision] = await client.search_emsal(kw, page_number=page)
            except Exception as exc:
                logger.warning("search_failed", extra={"keyword": kw, "page": page, "err": str(exc)[:120]})
                break
            if not decs:
                break
            new_in_page = 0
            for dec in decs:
                if n_docs >= limit:
                    break
                if dec.document_id in seen_ids:
                    continue
                seen_ids.add(dec.document_id)
                try:
                    text = await client.get_emsal_document(dec.document_id)
                except Exception as exc:
                    logger.warning("fetch_failed", extra={"id": dec.document_id, "err": str(exc)[:120]})
                    continue
                if not text or len(text) < 200:
                    continue
                # NOT: per-domain content filtresi kaldırıldı — UYAP'ın keyword-match'i
                # zaten relevance sinyali veriyor; istinaf prosedürel kararları bile
                # konuya referans içeriyor ve cross-encoder retrieval'da gerçek alakayı
                # sıralar. Yalın "non-empty + min 200 char" yeterli.
                chunks = chunk_decision(text)
                if not chunks:
                    continue
                base = {
                    "doc_id": f"u-{dec.document_id}",
                    "court": "uyap",
                    "chamber": dec.chamber,
                    "date": dec.date,
                    "title": dec.title,
                    "source": "uyap",
                    "source_url": dec.source_url,
                    "domain": domain,
                    "doc_type": "case",
                }
                for seq, c in enumerate(chunks):
                    cid = f"u-{dec.document_id}-c{seq}"
                    payload = {
                        **base, "chunk_id": cid, "chunk_seq": seq, "text": c.text,
                        "section": c.metadata.get("section", "gerekce"),
                    }
                    pending_chunks.append((c.text, cid, payload))
                n_docs += 1
                new_in_page += 1
                if len(pending_chunks) >= batch_chunks:
                    await _flush()
                logger.info("doc_added", extra={"id": dec.document_id, "kw": kw, "domain": domain, "n_docs": n_docs})
            if new_in_page == 0:
                break  # bu sayfa hep duplicate veya filter-rejected → sonraki keyword
            page += 1
    await _flush()
    return n_docs, n_chunks


async def _run(args: argparse.Namespace) -> int:
    logger.info("seed_started domain=%s limit=%d", args.domain, args.limit)
    logger.info("warming_embedder (BGE-M3 cuda)")
    embedder = Embedder()
    _ = embedder.encode(["sıcak başlatma"], batch_size=1)
    logger.info("embedder_ready")

    qdrant = get_client()
    try:
        await ensure_collection(qdrant)
        async with YargiClient() as client:
            n_docs, n_chunks = await _seed_domain(
                client, embedder, qdrant, args.domain, args.limit, args.batch_chunks,
            )
        logger.info("=" * 50)
        logger.info("UYAP SEED TOPLAM: %d karar, %d chunk (domain=%s)", n_docs, n_chunks, args.domain)
    finally:
        await qdrant.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.seed_uyap_emsal")
    parser.add_argument("--domain", choices=list(DOMAIN_KEYWORDS), default="tuketici")
    parser.add_argument("--limit", type=int, default=60, help="Domain başına maks. karar")
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
