"""HuggingFace seed — erdem-erdem/Turkish-Law-Documents-700k-clustered.

702.295 Yargıtay kararı, parquet, chamber bilgisi text içinde. Chamber'a göre
domain'lere filtrelenip seed edilir (CEZA daireleri scope dışı).

Kullanım:
    uv run python -m scripts.seed_hf_yargitay --shards 0 --cap-per-domain 500
    uv run python -m scripts.seed_hf_yargitay --shards 0,1,2 --cap-per-domain 800
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

# Windows: pyarrow'u torch'tan önce yükle.
from core import native_preload  # noqa: F401
from retrieval.chunker import chunk_decision
from retrieval.embedding import Embedder
from retrieval.vector_store import ChunkPoint, ensure_collection, get_client, upsert_chunks

logger = logging.getLogger("scripts.seed_hf_yargitay")

REPO = "erdem-erdem/Turkish-Law-Documents-700k-clustered"

# Yargıtay Hukuk Dairesi → in-scope domain (CEZA daireleri scope dışı, atlanır).
# Birden fazla domain'e uyan daire (örn. 3. HD = kira VE tüketici) — varsayılan
# olarak listenin ilk domain'i. Cap her domain için ayrı uygulanır.
CHAMBER_TO_DOMAIN: dict[str, str] = {
    # İş Hukuku
    "9. Hukuk Dairesi":  "isHukuku",
    "22. Hukuk Dairesi": "isHukuku",
    "21. Hukuk Dairesi": "isHukuku",
    "7. Hukuk Dairesi":  "isHukuku",
    "10. Hukuk Dairesi": "isHukuku",  # SGK alacakları
    # Tüketici
    "13. Hukuk Dairesi": "tuketici",  # eski tüketici dairesi
    "11. Hukuk Dairesi": "tuketici",  # tüketici/ticari (en hacimli)
    # Kira
    "3. Hukuk Dairesi":  "kira",
    "6. Hukuk Dairesi":  "kira",
    # İcra
    "12. Hukuk Dairesi": "icra",
    "19. Hukuk Dairesi": "icra",
    "23. Hukuk Dairesi": "icra",
    # Trafik
    "17. Hukuk Dairesi": "trafik",
    "4. Hukuk Dairesi":  "trafik",  # tazminat
    # Tapu
    "1. Hukuk Dairesi":  "tapu",
    "8. Hukuk Dairesi":  "tapu",
    "14. Hukuk Dairesi": "tapu",
    "20. Hukuk Dairesi": "tapu",
}

# Chamber'ı text başından çıkar — "**N. Hukuk Dairesi NNNN/NN E. , NNNN/NN K.**"
_CHAMBER_RE = re.compile(r"\*\*((\d+)\.\s+Hukuk Dairesi)\s+\d", re.I)


def _detect_chamber_domain(text: str) -> tuple[str | None, str | None]:
    """text'ten chamber + domain çıkar. Bulamazsa (None, None)."""
    m = _CHAMBER_RE.search(text[:400])
    if not m:
        return None, None
    chamber = m.group(1)
    return chamber, CHAMBER_TO_DOMAIN.get(chamber)


async def _run(args: argparse.Namespace) -> int:
    shards = [int(s) for s in args.shards.split(",")]
    cap = args.cap_per_domain
    logger.info("seed_started shards=%s cap_per_domain=%d", shards, cap)
    embedder = Embedder()
    _ = embedder.encode(["sıcak başlatma"], batch_size=1)
    logger.info("embedder_ready")

    qdrant = get_client()
    per_domain_count: dict[str, int] = {}
    seen_ids: set[str] = set()
    pending: list[tuple[str, str, dict]] = []
    n_total_docs = n_total_chunks = 0

    async def _flush() -> None:
        nonlocal n_total_chunks
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
        n_total_chunks += len(points)
        pending.clear()

    try:
        await ensure_collection(qdrant)
        for shard_idx in shards:
            fp = hf_hub_download(
                repo_id=REPO,
                filename=f"data/train-{shard_idx:05d}-of-00009.parquet",
                repo_type="dataset",
            )
            logger.info("shard_loaded idx=%d path=%s", shard_idx, fp)
            pf = pq.ParquetFile(fp)
            for batch in pf.iter_batches(batch_size=1000):
                texts = batch.column("text").to_pylist()
                ids = batch.column("id").to_pylist()
                esas_nos = batch.column("esasNo").to_pylist()
                karar_nos = batch.column("kararNo").to_pylist()
                karar_tarihleri = batch.column("kararTarihi").to_pylist()
                for txt, did, eno, kno, ktar in zip(texts, ids, esas_nos, karar_nos, karar_tarihleri):
                    if not txt or len(txt) < 200:
                        continue
                    chamber, domain = _detect_chamber_domain(txt)
                    if not domain:
                        continue
                    if per_domain_count.get(domain, 0) >= cap:
                        continue
                    sid = str(did)
                    if sid in seen_ids:
                        continue
                    seen_ids.add(sid)
                    chunks = chunk_decision(txt)
                    if not chunks:
                        continue
                    base = {
                        "doc_id": f"h-{sid}",
                        "court": "yargitay",
                        "chamber": chamber,
                        "date": ktar,
                        "title": f"{chamber} {eno}/{kno}",
                        "source": "yargitay",
                        "source_url": f"https://karararama.yargitay.gov.tr/?aranan={sid}",
                        "domain": domain,
                        "doc_type": "case",
                        "esas_no": eno,
                        "karar_no": kno,
                    }
                    for seq, c in enumerate(chunks):
                        cid = f"h-{sid}-c{seq}"
                        payload = {**base, "chunk_id": cid, "chunk_seq": seq,
                                   "text": c.text,
                                   "section": c.metadata.get("section", "gerekce")}
                        pending.append((c.text, cid, payload))
                    per_domain_count[domain] = per_domain_count.get(domain, 0) + 1
                    n_total_docs += 1
                    if len(pending) >= args.batch_chunks:
                        await _flush()
                    if n_total_docs % 200 == 0:
                        logger.info("progress docs=%d per_dom=%s", n_total_docs, per_domain_count)
                # Cap kontrol — tüm domain'ler dolduysa erken çık
                if all(per_domain_count.get(d, 0) >= cap for d in set(CHAMBER_TO_DOMAIN.values())):
                    logger.info("all_caps_reached early-stop")
                    break
        await _flush()
        logger.info("=" * 50)
        logger.info("HF YARGITAY SEED: %d karar, %d chunk", n_total_docs, n_total_chunks)
        for d, n in sorted(per_domain_count.items()):
            logger.info("  %s: %d karar", d, n)
    finally:
        await qdrant.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.seed_hf_yargitay")
    parser.add_argument("--shards", default="0", help="virgüllü liste: 0 veya 0,1,2 (max 0..8)")
    parser.add_argument("--cap-per-domain", type=int, default=500)
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
