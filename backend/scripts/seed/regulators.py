"""Düzenleyici otorite (regulator) karar seeding — Sprint-5 W15.

KVKK + Rekabet Kurumu + Sayıştay + GİB Özelge + (broken: BDDK / Sigorta Tahkim)
kararlarını **local yargi-mcp MCP tools** üzerinden çeker ve Qdrant'a
"regulator" payload field'ı ile yazar.

Sprint-5 başında plan manuel JSONL hazırlamak üzerine kuruluydu (W15.1-15.3).
W15 implementation sırasında local yargi-mcp v0.2.0+'ın 26 tool barındırdığı
keşfedildi: search_kvkk_decisions, search_rekabet_kurumu_decisions,
search_sayistay_unified, search_gib_ozelge tek MCP çağrısı ile binlerce
karar üretiyor. Manuel JSONL → MCP fetch refactor edildi.

Upstream durumu (2026-05-26):
    KVKK             : OK (10/sayfa, ~50 sayfa = 500 karar)
    Rekabet Kurumu   : OK (10/sayfa, ~100 sayfa = 1000 karar)
    Sayıştay (daire) : OK (20/sayfa, 7414 toplam record)
    GİB Özelge       : OK (20/sayfa, 18000+ özelge)
    BDDK             : BROKEN (Tavily 433 — maintainer side issue)
    Sigorta Tahkim   : BROKEN (Tavily 433 — maintainer side issue)
    SPK              : YOK (public MCP tool yok)

Kullanım:
    uv run python -m scripts.seed.regulators
    uv run python -m scripts.seed.regulators --regulator kvkk
    uv run python -m scripts.seed.regulators --regulator gib_ozelge --max-pages 50

Beklenen kayıt sayıları (hedef Sprint-5):
    KVKK     ~300  (30 sayfa × 10)
    Rekabet  ~300  (30 sayfa × 10)
    Sayıştay ~500  (25 sayfa × 20)
    GİB      ~400  (20 sayfa × 20)
    --------
    Toplam   ~1500 (BDDK/Sigorta hariç)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

from qdrant_client import AsyncQdrantClient

from agents.config import REGULATOR_TO_DOMAINS
from retrieval.chunker import chunk_decision
from retrieval.embedding import Embedder
from retrieval.vector_store import ChunkPoint, ensure_collection, get_client, upsert_chunks
from retrieval.yargi_client import RegulatorDecision, YargiClient

logger = logging.getLogger("scripts.seed.regulators")

# Çalışan regulator'lar (BDDK/sigorta_tahkim/spk dışında — upstream sorunlu)
ACTIVE_REGULATORS: tuple[str, ...] = (
    "kvkk",
    "rekabet",
    "sayistay",
    "gib_ozelge",
)

# Her domain için varsayılan keyword setleri — broad fetch için
REGULATOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "kvkk": (
        "veri güvenliği",
        "kişisel veri",
        "açık rıza",
        "veri ihlali",
        "veri sorumlusu",
        "aydınlatma yükümlülüğü",
        "veri silme",
        "ticari elektronik ileti",
    ),
    "rekabet": (
        "tüketici",
        "rekabet ihlali",
        "kartel",
        "yoğunlaşma",
        "muafiyet",
        "hâkim durum",
        "pazar payı",
        "anlaşma",
    ),
    "sayistay": (
        "belediye",
        "harcama",
        "ihale",
        "kamu zararı",
        "personel ödemesi",
        "ödenek aşımı",
        "satın alma",
        "kira",
    ),
    "gib_ozelge": (
        "KDV oranı",
        "gelir vergisi",
        "kurumlar vergisi",
        "ÖTV",
        "damga vergisi",
        "stopaj",
        "iade",
        "muafiyet",
        "istisna",
        "amortisman",
    ),
}

# Her regulator için karar başına maks. metin uzunluğu
MAX_TEXT_CHARS = 8000


@dataclass(slots=True)
class SeedStats:
    """Tek regulator için toplam istatistik."""

    fetched: int = 0
    chunks: int = 0
    errors: int = 0


async def _fetch_regulator_page(
    client: YargiClient,
    regulator: str,
    keyword: str,
    page: int,
) -> list[RegulatorDecision]:
    """Tek bir (regulator, keyword, page) için karar listesini çek."""
    try:
        if regulator == "kvkk":
            return await client.search_kvkk(keyword, page=page)
        if regulator == "rekabet":
            return await client.search_rekabet(keyword=keyword, page=page)
        if regulator == "sayistay":
            return await client.search_sayistay(keyword, decision_type="daire", page=page)
        if regulator == "gib_ozelge":
            return await client.search_gib_ozelge(keywords=keyword, page=page)
        logger.warning("unknown_regulator %s", regulator)
        return []
    except Exception as exc:
        logger.warning("regulator_fetch_failed %s/%s p=%d: %s", regulator, keyword, page, exc)
        return []


def _build_chunks_for_decision(
    decision: RegulatorDecision,
    domains: tuple[str, ...],
) -> list[tuple[str, str, dict[str, object]]]:
    """Tek karar için chunk list (chunk_id, text, payload).

    Text fallback chain:
        1. decision.text (search response'da varsa — Sayıştay web_karar_metni)
        2. decision.summary (KVKK description)
        3. decision.title (Rekabet — başlık tam karar özetidir, 200+ karakter)
    """
    text = (decision.text or decision.summary or decision.title or "").strip()
    if not text:
        return []
    # GİB özelgeler genellikle 5-8K karakter — chunker bunu otomatik böler.
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]

    decision_chunks = chunk_decision(text)
    if not decision_chunks:
        # Section marker bulunmadıysa text tek chunk olarak kabul et
        from retrieval.chunker import Chunk
        decision_chunks = [Chunk(text=text, seq=0, metadata={"section": "gerekce"})]

    primary_domain = domains[0] if domains else "idari"
    chunks_out: list[tuple[str, str, dict[str, object]]] = []
    for seq, ch in enumerate(decision_chunks):
        chunk_id = f"reg-{decision.regulator}-{decision.decision_id}-c{seq}"
        payload = {
            "doc_id": decision.id,
            "court": decision.regulator,
            "regulator": decision.regulator,
            "decision_type": "regulator",
            "chamber": None,
            "date": decision.date,
            "title": decision.title or "",
            "source": decision.regulator,
            "source_url": decision.source_url,
            "domain": primary_domain,
            "chunk_seq": seq,
            "text": ch.text,
            "section": ch.metadata.get("section", "gerekce"),
        }
        chunks_out.append((chunk_id, ch.text, payload))
    return chunks_out


async def _seed_regulator(
    regulator: str,
    *,
    max_pages: int,
    embedder: Embedder,
    qdrant: AsyncQdrantClient,
    client: YargiClient,
) -> SeedStats:
    """Tek bir regulator için tüm keyword'leri ve sayfaları seed et."""
    logger.info("regulator_started %s max_pages=%d", regulator, max_pages)
    stats = SeedStats()

    keywords = REGULATOR_KEYWORDS.get(regulator, ())
    if not keywords:
        logger.warning("regulator_no_keywords %s", regulator)
        return stats

    domains = REGULATOR_TO_DOMAINS.get(regulator, ("idari",))

    # Dedup: aynı decision_id farklı keyword'lerde tekrar gelebilir
    seen_ids: set[str] = set()
    chunks_buffer: list[tuple[str, str, dict[str, object]]] = []

    for keyword in keywords:
        for page in range(1, max_pages + 1):
            decisions = await _fetch_regulator_page(client, regulator, keyword, page)
            if not decisions:
                # Boş sayfa = bu keyword için bitti, bir sonrakine geç
                break
            new_count = 0
            for dec in decisions:
                if dec.decision_id in seen_ids:
                    continue
                seen_ids.add(dec.decision_id)
                new_count += 1
                stats.fetched += 1
                chunks = _build_chunks_for_decision(dec, domains)
                chunks_buffer.extend(chunks)
            logger.info(
                "regulator_page_fetched %s kw=%s p=%d new=%d total_fetched=%d",
                regulator, keyword[:20], page, new_count, stats.fetched,
            )
            # Eğer yeni karar yoksa bu keyword için bitti
            if new_count == 0:
                break

    if not chunks_buffer:
        logger.info("regulator_no_chunks %s", regulator)
        return stats

    # Embed batch (BGE-M3)
    texts = [c[1] for c in chunks_buffer]
    out = await asyncio.to_thread(embedder.encode, texts, 8)

    points = [
        ChunkPoint(
            id=chunk_id,
            dense_vector=dense,
            sparse_indices=sparse[0],
            sparse_values=sparse[1],
            payload=payload,
        )
        for (chunk_id, _text, payload), dense, sparse in zip(
            chunks_buffer, out.dense, out.sparse
        )
    ]

    await upsert_chunks(qdrant, points)
    stats.chunks = len(points)
    logger.info("regulator_upserted %s chunks=%d", regulator, stats.chunks)
    return stats


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed regulator decisions via local yargi-mcp")
    parser.add_argument(
        "--regulator",
        choices=("all", *ACTIVE_REGULATORS),
        default="all",
        help="Seed edilecek regulator (default: all)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Her keyword için maks. sayfa sayısı (default: 5)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    targets = ACTIVE_REGULATORS if args.regulator == "all" else (args.regulator,)
    logger.info("regulator_seed_started targets=%s max_pages=%d", targets, args.max_pages)

    embedder = Embedder()
    _ = embedder.encode(["sıcak başlatma"], batch_size=1)
    logger.info("embedder_ready")

    qdrant = get_client()
    total_chunks = 0
    total_fetched = 0
    try:
        await ensure_collection(qdrant)
        async with YargiClient() as client:
            for reg in targets:
                try:
                    stats = await _seed_regulator(
                        reg,
                        max_pages=args.max_pages,
                        embedder=embedder,
                        qdrant=qdrant,
                        client=client,
                    )
                    total_chunks += stats.chunks
                    total_fetched += stats.fetched
                except Exception as exc:
                    logger.exception("regulator_seed_failed %s: %s", reg, exc)
        logger.info("=" * 60)
        logger.info(
            "REGULATOR TOPLAM: %d karar / %d chunk (regulators=%s)",
            total_fetched, total_chunks, targets,
        )
    finally:
        await qdrant.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
