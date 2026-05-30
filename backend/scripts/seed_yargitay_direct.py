"""Direct karararama.yargitay.gov.tr POST API seed.

Public POST endpoint (auth yok, CAPTCHA yok per agent araştırması):
  POST /aramadetaylist
  Headers: X-Requested-With: XMLHttpRequest, X-KL-KIS-Ajax-Request: Ajax_Request
  Body: {"data": {arananKelime, birimYrgKurulDaire, baslangicTarihi, bitisTarihi,
                  pageSize, pageNumber}}

Bu, yargi-mcp Bedesten'in 9-doc/keyword cap'ini bypass eder ve chamber filtresiyle
substantive consumer/iş/kira Yargıtay kararlarını çeker.

Kullanım: uv run python -m scripts.seed_yargitay_direct --domain tuketici --cap 200
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

import httpx

from core import native_preload  # noqa: F401
from retrieval.chunker import chunk_decision
from retrieval.embedding import Embedder
from retrieval.vector_store import ChunkPoint, ensure_collection, get_client, upsert_chunks

logger = logging.getLogger("scripts.seed_yargitay_direct")

SEARCH_URL = "https://karararama.yargitay.gov.tr/aramadetaylist"
DOC_URL = "https://karararama.yargitay.gov.tr/getDokuman"

HEADERS = {
    "Content-Type": "application/json; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "X-KL-KIS-Ajax-Request": "Ajax_Request",
    "User-Agent": "adalet-agent/0.1 (ders projesi)",
    "Accept": "application/json, text/plain, */*",
}

# Domain → (chamber list, keyword list)
# Emsal corpus gap analizi (2026-05-30): corpus %75 Anayasa, Yargıtay tüketici/iş
# kararları eksik. Keyword listeleri genişletildi — her domain için 8-10 sorgu.
DOMAIN_CONFIG: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "tuketici": (
        ("3. Hukuk Dairesi", "13. Hukuk Dairesi", "11. Hukuk Dairesi", "Hukuk Genel Kurulu"),
        (
            "ayıplı mal",
            "ayıplı hizmet",
            "tüketici hakem heyeti",
            "tüketici mahkemesi",
            "garanti süresi",
            "cayma hakkı",
            "mesafeli sözleşme",
            "TKHK madde",
            "araç ayıplı",
            "ayıplı yapı",
        ),
    ),
    "isHukuku": (
        ("9. Hukuk Dairesi", "22. Hukuk Dairesi", "21. Hukuk Dairesi", "Hukuk Genel Kurulu"),
        (
            "kıdem tazminatı",
            "ihbar tazminatı",
            "haksız fesih",
            "işe iade",
            "fazla mesai",
            "yıllık izin ücreti",
            "iş akdi feshi",
            "kötüniyet tazminatı",
            "sendikal tazminat",
            "mobbing",
        ),
    ),
    "kira": (
        ("3. Hukuk Dairesi", "6. Hukuk Dairesi", "Hukuk Genel Kurulu"),
        (
            "kira tahliye",
            "kira artış",
            "ecrimisil",
            "kira tespiti",
            "kiracı tahliye",
            "depozito iadesi",
        ),
    ),
    "trafik": (
        ("17. Hukuk Dairesi", "4. Hukuk Dairesi"),
        (
            "trafik kazası",
            "kasko",
            "destekten yoksun kalma",
            "zorunlu trafik sigortası",
            "bedensel zarar trafik",
        ),
    ),
    "icra": (
        ("12. Hukuk Dairesi", "19. Hukuk Dairesi"),
        (
            "ödeme emri",
            "haciz",
            "icra itirazı",
            "itirazın iptali",
            "borçtan kurtulma",
        ),
    ),
    "tapu": (
        ("1. Hukuk Dairesi", "8. Hukuk Dairesi", "14. Hukuk Dairesi"),
        (
            "tapu iptali",
            "müdahalenin men'i",
            "izale-i şuyu",
            "tapu tescil",
            "ön alım hakkı",
        ),
    ),
}

DATE_WINDOWS: tuple[tuple[str, str], ...] = (
    ("01.01.2024", "31.12.2026"),  # son 2 yıl — HF dataset'in cutoff sonrası
    ("01.01.2022", "31.12.2023"),
)


async def _search(client: httpx.AsyncClient, chamber: str, kw: str,
                  d_start: str, d_end: str, page: int) -> list[dict[str, Any]]:
    payload = {
        "data": {
            "arananKelime": kw,
            "birimYrgKurulDaire": chamber,
            "baslangicTarihi": d_start,
            "bitisTarihi": d_end,
            "pageSize": 10,
            "pageNumber": page,
        }
    }
    try:
        r = await client.post(SEARCH_URL, json=payload, headers=HEADERS, timeout=30.0)
        r.raise_for_status()
        data = r.json()
        # API response: {"data": {"data": [...], "recordsTotal": N, ...}}
        return list((data.get("data") or {}).get("data") or [])
    except Exception as exc:
        logger.warning("search_failed chamber=%s kw=%s page=%d err=%s",
                       chamber, kw, page, str(exc)[:120])
        return []


async def _fetch_doc(client: httpx.AsyncClient, doc_id: str) -> str:
    """Karar tam metnini çek (HTML, raw text döndür)."""
    try:
        r = await client.get(DOC_URL, params={"id": doc_id}, headers=HEADERS, timeout=30.0)
        r.raise_for_status()
        data = r.json()
        # Beklenen şema: {"data": "<html>..." or markdown}
        text = (data.get("data") or "")
        if isinstance(text, str):
            # HTML temizle
            import re
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s{2,}", " ", text)
            return text.strip()
        return str(text)
    except Exception as exc:
        logger.warning("fetch_failed id=%s err=%s", doc_id, str(exc)[:120])
        return ""


async def _seed_domain(client: httpx.AsyncClient, embedder: Embedder,
                       qdrant, domain: str, cap: int, batch_chunks: int) -> tuple[int, int]:
    chambers, keywords = DOMAIN_CONFIG[domain]
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
            ChunkPoint(id=cid, dense_vector=dense,
                       sparse_indices=sparse[0], sparse_values=sparse[1],
                       payload=payload)
            for (_, cid, payload), dense, sparse in zip(pending, out.dense, out.sparse)
        ]
        await upsert_chunks(qdrant, points)
        n_chunks += len(points)
        pending.clear()

    for chamber in chambers:
        if n_docs >= cap:
            break
        for kw in keywords:
            if n_docs >= cap:
                break
            for ds, de in DATE_WINDOWS:
                if n_docs >= cap:
                    break
                page = 1
                while n_docs < cap:
                    items = await _search(client, chamber, kw, ds, de, page)
                    if not items:
                        break
                    new_in_page = 0
                    for it in items:
                        if n_docs >= cap:
                            break
                        did = str(it.get("id") or "")
                        if not did or did in seen_ids:
                            continue
                        seen_ids.add(did)
                        text = await _fetch_doc(client, did)
                        if not text or len(text) < 300:
                            continue
                        chunks = chunk_decision(text)
                        if not chunks:
                            continue
                        eno = it.get("esasNo") or ""
                        kno = it.get("kararNo") or ""
                        ktar = it.get("kararTarihi") or ""
                        base = {
                            "doc_id": f"y-direct-{did}",
                            "court": "yargitay",
                            "chamber": chamber,
                            "date": ktar,
                            "title": f"{chamber} {eno}/{kno}",
                            "source": "yargitay",
                            "source_url": f"https://karararama.yargitay.gov.tr/?aranan={did}",
                            "domain": domain,
                            "doc_type": "case",
                            "esas_no": eno,
                            "karar_no": kno,
                        }
                        for seq, c in enumerate(chunks):
                            cid = f"y-direct-{did}-c{seq}"
                            payload = {**base, "chunk_id": cid, "chunk_seq": seq,
                                       "text": c.text,
                                       "section": c.metadata.get("section", "gerekce")}
                            pending.append((c.text, cid, payload))
                        n_docs += 1
                        new_in_page += 1
                        if len(pending) >= batch_chunks:
                            await _flush()
                        if n_docs % 20 == 0:
                            logger.info("progress n_docs=%d chamber=%s kw=%s", n_docs, chamber, kw)
                    if new_in_page == 0:
                        break
                    page += 1
    await _flush()
    return n_docs, n_chunks


async def _run(args: argparse.Namespace) -> int:
    logger.info("seed_started direct_yargitay domain=%s cap=%d", args.domain, args.cap)
    embedder = Embedder()
    _ = embedder.encode(["sıcak başlatma"], batch_size=1)
    logger.info("embedder_ready")
    qdrant = get_client()
    try:
        await ensure_collection(qdrant)
        async with httpx.AsyncClient() as client:
            n_docs, n_chunks = await _seed_domain(client, embedder, qdrant,
                                                  args.domain, args.cap, args.batch_chunks)
        logger.info("=" * 50)
        logger.info("DIRECT YARGITAY SEED: %d karar, %d chunk (domain=%s)",
                    n_docs, n_chunks, args.domain)
    finally:
        await qdrant.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.seed_yargitay_direct")
    parser.add_argument("--domain", choices=list(DOMAIN_CONFIG), default="tuketici")
    parser.add_argument("--cap", type=int, default=200)
    parser.add_argument("--batch-chunks", type=int, default=200)
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
