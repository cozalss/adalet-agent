"""Offline RAPTOR tree builder — Sprint-4 W3.1.

Qdrant'taki mevcut chunks → RAPTOR hiyerarşik özet ağacı → pickle.
Build pahalı (her cluster için LLM çağrısı + embed); production'da bir kez,
sonra runtime'da `RaptorIndex.load()` ile diskten yüklenir.

Çalıştırma:
    # 1) llama-server arka planda çalışıyor (RTX 4070)
    # 2) Qdrant arka planda çalışıyor (Docker)
    # 3) Build (default: emsal chunks, max 800 leaf — VRAM kontrolü için)
    RAPTOR_ENABLED=1 LLM_MODE=llamacpp_server \\
      uv run python -m scripts.build_raptor \\
        --max-chunks 800 \\
        --source case \\
        --out data/raptor/tree.pkl

Args:
    --max-chunks   leaf seviyesinde maximum chunk (VRAM gereken default 800)
    --source       case | law | all — Qdrant'tan hangi doc_type'lar çekilsin
    --domain       opsiyonel — sadece bu domain (örn. isHukuku) chunk'ları
    --out          pickle çıktı yolu (default data/raptor/tree.pkl)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from retrieval.raptor import RaptorIndex
from retrieval.vector_store import COLLECTION_NAME, get_client

DEFAULT_OUT = Path(__file__).parent.parent / "data" / "raptor" / "tree.pkl"


async def _fetch_chunks(
    source: str, domain: str | None, max_chunks: int,
) -> list[tuple[str, str]]:
    """Qdrant'tan chunk'ları topla. (chunk_id, text) çiftleri döner.

    Source filter:
        - case  → doc_type=='case' VEYA source ∈ {anayasa,yargitay,danistay}
        - law   → doc_type=='law'  VEYA source=='mevzuat'
        - all   → ikisi de
    """
    from qdrant_client import models  # type: ignore[import-untyped]

    client = get_client()
    try:
        # Qdrant scroll API — payload filter ile streaming
        filter_must: list = []
        if domain:
            filter_must.append(
                models.FieldCondition(
                    key="domain", match=models.MatchValue(value=domain),
                ),
            )

        # source filter ya Qdrant'ta uygula ya post-filter
        # Pratikte payload field'ları seed'lere göre değişiyor; post-filter daha sağlam.
        qdrant_filter = models.Filter(must=filter_must) if filter_must else None

        all_chunks: list[tuple[str, str]] = []
        offset = None
        batch_size = 200
        while len(all_chunks) < max_chunks:
            records, offset = await client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=qdrant_filter,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not records:
                break

            for rec in records:
                payload = rec.payload or {}
                text = payload.get("text", "")
                if not text or len(text) < 100:
                    continue
                doc_type = payload.get("doc_type", "")
                src = payload.get("source", "")

                # Source filter (post-fetch)
                if source == "case":
                    is_case = (
                        doc_type == "case"
                        or src in {"anayasa", "yargitay", "danistay", "bedesten"}
                    )
                    if not is_case:
                        continue
                elif source == "law":
                    is_law = doc_type == "law" or src == "mevzuat"
                    if not is_law:
                        continue
                # "all" → her şey kabul

                chunk_id = payload.get("chunk_id") or str(rec.id)
                all_chunks.append((chunk_id, text))
                if len(all_chunks) >= max_chunks:
                    break

            if offset is None:
                break

        return all_chunks
    finally:
        await client.close()


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="RAPTOR offline build")
    parser.add_argument(
        "--max-chunks", type=int, default=800,
        help="Leaf seviyesinde max chunk (default 800, VRAM kontrolü)",
    )
    parser.add_argument(
        "--source", choices=("case", "law", "all"), default="case",
        help="Hangi doc_type'lar (default case — uzun karar metinleri için)",
    )
    parser.add_argument(
        "--domain", default=None,
        help="Sadece bu domain (örn. isHukuku); None ise tüm domainler",
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT),
        help=f"Pickle çıktı yolu (default {DEFAULT_OUT})",
    )
    args = parser.parse_args()

    # RAPTOR_ENABLED check — build için zorunlu
    if os.environ.get("RAPTOR_ENABLED", "0") not in {"1", "true", "yes"}:
        print(
            "[!] RAPTOR_ENABLED env=0; build no-op çalışır. Aç: "
            "`set RAPTOR_ENABLED=1`",
            file=sys.stderr,
        )
        return 1

    print(f"[*] Qdrant'tan chunks çekiliyor "
          f"(source={args.source}, domain={args.domain}, max={args.max_chunks})...")
    chunks = await _fetch_chunks(args.source, args.domain, args.max_chunks)
    if not chunks:
        print("[!] Hiç chunk bulunamadı. Seed'ler eksik mi?", file=sys.stderr)
        return 1
    print(f"[*] {len(chunks)} chunk hazır → RAPTOR build başlıyor...")

    idx = RaptorIndex()
    await idx.build(chunks)
    print(f"[*] Build tamam. Seviye sayısı: {len(idx.tree)}, "
          f"toplam node: {len(idx.all_nodes())}")

    out_path = Path(args.out)
    idx.save(out_path)
    print(f"[OK] Pickle yazıldı: {out_path}")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
