"""Danıştay kararlarını doğrudan seed et — vergi ve idari hukuk.

Yargıtay seed scripti (seed_yargitay_direct.py) ile aynı mantık;
fark: Danıştay API endpoint'leri ve daire yapısı farklı.

Vergi ve idari hukuk davaları Danıştay'da görülür:
  - Vergi: Danıştay 7. Daire (KDV, GV), 9. Daire (Vergi Usul)
  - İdari: Danıştay 5. Daire (personel), 10. Daire (genel idari)

Çalıştırma:
    uv run python -m scripts.seed_danistay_direct --domain vergi --cap 80
    uv run python -m scripts.seed_danistay_direct --domain idari --cap 80
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import native_preload  # noqa: F401

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

SEARCH_URL = "https://karararama.danistay.gov.tr/aramadetaylist"
DOC_URL    = "https://karararama.danistay.gov.tr/getDokuman"
HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://karararama.danistay.gov.tr",
    "Referer": "https://karararama.danistay.gov.tr/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
CHUNK_CHARS = 800
OVERLAP     = 100

DOMAIN_CONFIG: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "vergi": (
        ("7. Daire", "9. Daire", "Vergi Dava Daireleri Kurulu"),
        (
            "katma değer vergisi",
            "gelir vergisi kesintisi",
            "vergi cezası",
            "re'sen tarhiyat",
            "vergi ziyaı cezası",
            "özel usulsüzlük",
            "kurumlar vergisi",
            "vergi incelemesi",
        ),
    ),
    "idari": (
        ("5. Daire", "10. Daire", "İdari Dava Daireleri Kurulu"),
        (
            "iptal davası",
            "idari işlem iptali",
            "disiplin cezası",
            "memuriyet ihraç",
            "devlet memuru",
            "görevden uzaklaştırma",
        ),
    ),
}

DATE_WINDOWS = (
    ("01.01.2024", "31.12.2026"),
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
    for attempt, wait_s in enumerate([0, 10, 30, 60], start=1):
        if wait_s:
            logger.info("rate_limit_backoff attempt=%d wait_s=%d kw=%s", attempt, wait_s, kw)
            await asyncio.sleep(wait_s)
        try:
            r = await client.post(SEARCH_URL, json=payload, headers=HEADERS, timeout=30.0)
            if r.status_code == 429:
                continue
            r.raise_for_status()
            data = r.json()
            return list((data.get("data") or {}).get("data") or [])
        except Exception as exc:
            logger.warning("search_failed kw=%s attempt=%d err=%s", kw, attempt, str(exc)[:80])
            if attempt == 4:
                return []
    return []


async def _fetch_doc(client: httpx.AsyncClient, doc_id: str, keyword: str = "") -> str:
    for attempt, wait_s in enumerate([0, 5, 15], start=1):
        if wait_s:
            await asyncio.sleep(wait_s)
        try:
            r = await client.get(DOC_URL, params={"id": doc_id, "arananKelime": keyword},
                                 headers=HEADERS, timeout=30.0)
            if r.status_code == 429:
                continue
            r.raise_for_status()
            data = r.json()
            text = (data.get("data") or "")
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s{2,}", " ", text).strip()
            return text
        except Exception as exc:
            logger.warning("fetch_failed id=%s err=%s", doc_id, str(exc)[:80])
            if attempt == 3:
                return ""
    return ""


def _chunk_text(text: str, chunk_size: int = CHUNK_CHARS, overlap: int = OVERLAP) -> list[str]:
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = end - overlap
    return chunks


async def main(args: argparse.Namespace) -> None:
    from retrieval.embedding import Embedder
    from retrieval.vector_store import ensure_collection, get_client, upsert_chunks
    from retrieval.hybrid_search import SearchResult

    domain = args.domain
    chambers, keywords = DOMAIN_CONFIG[domain]

    qdrant = get_client()
    await ensure_collection(qdrant)

    embedder = Embedder()
    seen_ids: set[str] = set()
    all_chunks: list[dict] = []

    async with httpx.AsyncClient() as client:
        for kw in keywords:
            for chamber in chambers:
                for d_start, d_end in DATE_WINDOWS:
                    if len(seen_ids) >= args.cap:
                        break
                    decisions = await _search(client, chamber, kw, d_start, d_end, 1)
                    await asyncio.sleep(0.5)

                    for dec in decisions:
                        doc_id = str(dec.get("id") or dec.get("docId") or "")
                        if not doc_id or doc_id in seen_ids:
                            continue
                        seen_ids.add(doc_id)

                        text = await _fetch_doc(client, doc_id, keyword=kw)
                        await asyncio.sleep(0.3)
                        if len(text) < 100:
                            continue

                        chunks = _chunk_text(text)
                        for i, chunk in enumerate(chunks):
                            cid = hashlib.sha1(f"danistay-{doc_id}-{i}".encode()).hexdigest()
                            all_chunks.append({
                                "id": cid,
                                "text": chunk,
                                "source": "danistay",
                                "domain": domain,
                                "doc_id": doc_id,
                                "chamber": chamber,
                                "keyword": kw,
                            })

                        if len(seen_ids) % 10 == 0:
                            logger.info("progress n_docs=%d n_chunks=%d", len(seen_ids), len(all_chunks))

    if not all_chunks:
        logger.warning("Hiç chunk bulunamadı!")
        return

    # Batch embed + upsert
    logger.info("Embedding %d chunk...", len(all_chunks))
    BATCH = 16
    from retrieval.vector_store import ChunkPoint
    points = []
    for i in range(0, len(all_chunks), BATCH):
        batch = all_chunks[i:i + BATCH]
        texts = [c["text"] for c in batch]
        out = await asyncio.to_thread(embedder.encode, texts, 8)
        for c, dense, sparse in zip(batch, out.dense, out.sparse):
            points.append(ChunkPoint(
                id=c["id"],
                dense_vector=dense,
                sparse_vector=sparse,
                payload={k: v for k, v in c.items() if k != "id"},
            ))

    await upsert_chunks(qdrant, points)
    logger.info("=" * 50)
    logger.info("DANISTAY SEED: %d karar, %d chunk (domain=%s)", len(seen_ids), len(all_chunks), domain)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Danıştay vergi/idari kararları seed")
    parser.add_argument("--domain", choices=list(DOMAIN_CONFIG), default="vergi")
    parser.add_argument("--cap", type=int, default=80)
    asyncio.run(main(parser.parse_args()))
