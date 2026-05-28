"""HuggingFace Danıştay seed — muhamparlak/turkish-law-bge-m3-embeddings.

Dataset sıralı: Yargıtay başta, Danıştay son shard'larda (kaynak alanı).
Danıştay kararları idari + vergi domain'lerini doldurur (corpus'ta en zayıf ikisi).
Chamber routing: Danıştay 3./4./7./9. Daire = vergi davaları → vergi; gerisi → idari.

NOT: Dataset'te pre-computed BGE-M3 `vector` var ama sparse YOK. Mevcut corpus
hybrid (dense+sparse) olduğundan tutarlılık için TEXT yeniden embed edilir
(seed_hf_yargitay ile aynı pipeline).

Kullanım:
    uv run python -m scripts.seed_danistay_hf --cap-per-domain 2000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download

# Windows: pyarrow'u torch'tan önce yükle.
from core import native_preload  # noqa: F401
from retrieval.chunker import chunk_decision
from retrieval.embedding import Embedder
from retrieval.vector_store import ChunkPoint, ensure_collection, get_client, upsert_chunks

logger = logging.getLogger("scripts.seed_danistay_hf")

REPO = "muhamparlak/turkish-law-bge-m3-embeddings"
CONFIG_PREFIX = "emsal_kararlar/"

# Danıştay metni chamber'ı Türkçe yazıyla verir ("BEŞİNCİ DAİRE"), numerik değil
# → chamber-tabanlı routing güvenilmez. İçerik-tabanlı: güçlü vergi terimleri
# varsa vergi, yoksa idari (genel idari hukuk). Markerlar incidental "vergi"
# kelimesinden ayırt edici (tarhiyat, matrah, KDV, vergi ziyaı vb.).
_VERGI_MARKERS = (
    "tarhiyat", "vergi ziya", "matrah", "katma değer vergisi", "gelir vergisi",
    "kurumlar vergisi", "vergi mahkemesi", "vergi dairesi", "vergi dava",
    "beyanname", "özel usulsüzlük", "ihtirazi kayıt", "re'sen tarh",
    "katma değer", "stopaj", "ötv", "özel tüketim vergisi", "damga vergisi",
)


def _route_danistay(text: str) -> str:
    """Danıştay kararını İÇERİĞE göre domain'e yönlendir (vergi vs idari).

    İlk ~1500 char'da güçlü vergi terimi varsa vergi; yoksa idari (genel idari).
    Chamber Türkçe-yazı formatında (numerik değil) → içerik daha güvenilir.
    """
    head = text[:1500].lower()
    if any(m in head for m in _VERGI_MARKERS):
        return "vergi"
    return "idari"


def _danistay_shards() -> list[str]:
    """Dataset'teki emsal shard'larını sırala — Danıştay sondadır, tersten tara."""
    api = HfApi()
    info = api.dataset_info(REPO)
    shards = sorted(
        s.rfilename for s in info.siblings
        if s.rfilename.startswith(CONFIG_PREFIX) and s.rfilename.endswith(".parquet")
    )
    return list(reversed(shards))  # Danıştay'lı son shard'lar önce


async def _run(args: argparse.Namespace) -> int:
    cap = args.cap_per_domain
    logger.info("seed_started cap_per_domain=%d", cap)
    embedder = Embedder()
    _ = embedder.encode(["sıcak başlatma"], batch_size=1)
    logger.info("embedder_ready")

    qdrant = get_client()
    per_domain: dict[str, int] = {"idari": 0, "vergi": 0}
    seen: set[str] = set()
    pending: list[tuple[str, str, dict]] = []
    n_docs = n_chunks = 0
    targets = {"idari", "vergi"}

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

    try:
        await ensure_collection(qdrant)
        for shard in _danistay_shards():
            if all(per_domain[d] >= cap for d in targets):
                logger.info("all_caps_reached early-stop")
                break
            fp = hf_hub_download(REPO, shard, repo_type="dataset")
            logger.info("shard_loaded %s", shard)
            pf = pq.ParquetFile(fp)
            for batch in pf.iter_batches(
                batch_size=1000,
                columns=["doc_id", "text", "kaynak", "esas_no", "karar_no", "tarih"],
            ):
                kaynaks = batch.column("kaynak").to_pylist()
                texts = batch.column("text").to_pylist()
                ids = batch.column("doc_id").to_pylist()
                esas = batch.column("esas_no").to_pylist()
                karar = batch.column("karar_no").to_pylist()
                tarih = batch.column("tarih").to_pylist()
                for kyn, txt, did, eno, kno, tar in zip(
                    kaynaks, texts, ids, esas, karar, tarih,
                ):
                    if not str(kyn).startswith("Dan"):
                        continue  # yalnız Danıştay (kaynak="Danıştay")
                    if not txt or len(txt) < 200:
                        continue
                    domain = _route_danistay(txt)
                    if per_domain[domain] >= cap:
                        continue
                    sid = str(did)
                    if sid in seen:
                        continue
                    seen.add(sid)
                    chunks = chunk_decision(txt)
                    if not chunks:
                        continue
                    base = {
                        "doc_id": f"dn-{sid}",
                        "court": "danistay",
                        "chamber": None,
                        "date": tar,
                        "title": f"Danıştay {eno}/{kno}",
                        "source": "danistay",
                        "source_url": "https://karararama.danistay.gov.tr/",
                        "domain": domain,
                        "doc_type": "case",
                        "esas_no": eno,
                        "karar_no": kno,
                    }
                    for seq, c in enumerate(chunks):
                        cid = f"dn-{sid}-c{seq}"
                        payload = {**base, "chunk_id": cid, "chunk_seq": seq,
                                   "text": c.text,
                                   "section": c.metadata.get("section", "gerekce")}
                        pending.append((c.text, cid, payload))
                    per_domain[domain] += 1
                    n_docs += 1
                    if len(pending) >= args.batch_chunks:
                        await _flush()
                    if n_docs % 200 == 0:
                        logger.info("progress docs=%d per_dom=%s", n_docs, per_domain)
                if all(per_domain[d] >= cap for d in targets):
                    break
        await _flush()
        logger.info("=" * 50)
        logger.info("DANISTAY SEED: %d karar, %d chunk | per_dom=%s",
                    n_docs, n_chunks, per_domain)
    finally:
        await qdrant.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.seed_danistay_hf")
    parser.add_argument("--cap-per-domain", type=int, default=2000)
    parser.add_argument("--batch-chunks", type=int, default=300)
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
