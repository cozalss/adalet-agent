"""#2 DOĞRULAMA: law chunk'larını sub-split + re-embed → test koleksiyonu (ölçüm-sürücülü, 2026-06-04).

Hipotez (#2, commit 5ede892): uzun çok-fıkralı maddeler tek dev chunk → dense vektör dilüe →
spesifik madde alçak rank. Sub-split (chunk_mevzuat fix) madde sinyalini keskinleştirir.
Bu script mevcut law chunk'larını (mursit_hybrid'den) çekip uzunları sub-split eder, Mursit dense +
BGE-M3 sparse ile RE-EMBED edip test koleksiyonuna yazar. Sonra benchmark A/B: eski vs sub-chunked.

Çalıştır: cd backend && uv run python -m scripts.exp_subchunk_reseed
Sonra:    QDRANT_COLLECTION=adalet_subchunk_test uv run python -m scripts.run_baseline --mode hybrid
          (EVAL_DOC_TYPE=law ile; %35.4 hybrid+law baseline ile kıyas)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from qdrant_client import QdrantClient, models

import core.native_preload  # noqa: F401
from retrieval.chunker import _MEVZUAT_SUBCHUNK_THRESHOLD, chunk_text
from retrieval.hybrid_search import _get_embedder, _get_sparse_embedder

SRC = "adalet_mursit_hybrid"
DST = "adalet_subchunk_test"
BATCH = 64


def _scroll_law(client: QdrantClient) -> list[dict]:
    """doc_type=law tüm chunk'ları (payload + text) çek."""
    out, offset = [], None
    flt = models.Filter(must=[models.FieldCondition(
        key="doc_type", match=models.MatchValue(value="law"))])
    while True:
        pts, offset = client.scroll(SRC, scroll_filter=flt, limit=512,
                                    offset=offset, with_payload=True, with_vectors=False)
        out.extend({"id": p.id, "payload": dict(p.payload or {})} for p in pts)
        if offset is None:
            break
    return out


def _subsplit(rows: list[dict]) -> list[dict]:
    """Uzun maddeleri sub-split; her sub-chunk payload'u korur (madde_no/kanun_kodu/doc_type)."""
    out = []
    seq = 0
    for r in rows:
        pl = r["payload"]
        text = pl.get("text", "")
        if not text:
            continue
        parts = ([text] if len(text) <= _MEVZUAT_SUBCHUNK_THRESHOLD
                 else (chunk_text(text, chunk_chars=1000, overlap_chars=150) or [text]))
        for part in parts:
            np = dict(pl)
            np["text"] = part
            np["chunk_id"] = f"sub-{seq}"
            out.append({"id": seq, "payload": np})
            seq += 1
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = QdrantClient(url="http://localhost:6333", timeout=60)

    print(f"[1] {SRC}'den law chunk'lari cekiliyor...", flush=True)
    law = _scroll_law(client)
    print(f"    {len(law)} law chunk", flush=True)

    print("[2] Uzun maddeler sub-split ediliyor...", flush=True)
    subs = _subsplit(law)
    longn = sum(1 for r in law if len(r['payload'].get('text', '')) > _MEVZUAT_SUBCHUNK_THRESHOLD)
    print(f"    {len(law)} -> {len(subs)} chunk ({longn} uzun madde alt-bolundu)", flush=True)

    print(f"[3] Test koleksiyonu olusturuluyor ({DST})...", flush=True)
    client.recreate_collection(
        DST,
        vectors_config={"dense": models.VectorParams(size=768, distance=models.Distance.COSINE)},
        sparse_vectors_config={"sparse": models.SparseVectorParams()},
    )

    print("[4] Re-embed (Mursit dense + BGE-M3 sparse) + upsert...", flush=True)
    dense_emb = _get_embedder()
    sparse_emb = _get_sparse_embedder()
    for i in range(0, len(subs), BATCH):
        chunk = subs[i:i + BATCH]
        texts = [c["payload"]["text"] for c in chunk]
        d_out = dense_emb.encode(texts)          # Mursit dense (768)
        s_out = sparse_emb.encode(texts)         # BGE-M3 (sparse alınır)
        points = []
        for c, dv, (sidx, sval) in zip(chunk, d_out.dense, s_out.sparse):
            vec = {"dense": list(dv)}
            if sidx:
                vec["sparse"] = models.SparseVector(indices=list(sidx), values=list(sval))
            points.append(models.PointStruct(id=c["id"], vector=vec, payload=c["payload"]))
        client.upsert(DST, points=points)
        if (i // BATCH) % 20 == 0:
            print(f"    ...{i + len(chunk)}/{len(subs)}", flush=True)

    cnt = client.count(DST).count
    print(f"[5] TAMAM: {DST} = {cnt} nokta. Simdi benchmark:", flush=True)
    print(f"    QDRANT_COLLECTION={DST} EVAL_DOC_TYPE=law uv run python -m scripts.run_baseline --mode hybrid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
