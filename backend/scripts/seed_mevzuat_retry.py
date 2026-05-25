"""seed_mevzuat üzerine ince retry+backoff sarmalayıcı.

mevzuat-mcp public endpoint zaman zaman rate-limit veya cache-miss yüzünden
search_mevzuat sonucu boş döner. Bu script:

  1. seed_mevzuat'taki TARGET_LAWS'ı domain bazlı paketler halinde böler
  2. Her paketten önce 3 saniye sleep
  3. Her kanun için max 3 retry (exponential backoff: 5s, 10s, 20s)
  4. Hangi kanunlar başarıyla geldi/atlandı → JSON rapor yazar
  5. Zaten Qdrant'ta olan kanunları skip eder (idempotent)

Çalıştır:
    uv run python -m scripts.seed_mevzuat_retry [--only HMK,IYUK]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sys
from pathlib import Path

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("seed_retry")


async def _existing_kanun_kodlari(client) -> set[str]:
    """Qdrant'ta hangi kanun_kodu değerleri zaten var?"""
    from retrieval.vector_store import COLLECTION_NAME
    out: set[str] = set()
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=COLLECTION_NAME, limit=512,
            offset=offset, with_payload=True, with_vectors=False,
        )
        if not points:
            break
        for p in points:
            kk = (p.payload or {}).get("kanun_kodu")
            if kk:
                out.add(str(kk))
        if offset is None:
            break
    return out


async def _seed_one(
    kanun_kodu: str, kanun_adi: str, embedder, max_retries: int = 3,
) -> tuple[str, int, str]:
    """Tek kanunu retry+backoff ile çek. (kod, eklenen_madde, status) döner.

    seed_mevzuat:_seed_one_law'ı tek bir kanun için wrap eder — id_find,
    fetch, parse, upsert tek call. Hata varsa exponential backoff (5s, 10s,
    20s) ile yeniden dener.
    """
    from retrieval.mevzuat_client import KANUN_KODU_TO_NUMARA, MevzuatClient
    from retrieval.vector_store import ensure_collection, get_client
    from scripts.seed_mevzuat import _seed_one_law

    if kanun_kodu not in KANUN_KODU_TO_NUMARA:
        return (kanun_kodu, 0, "unknown_kanun_kodu")

    delay = 5
    last_err = "no_attempt"
    for attempt in range(1, max_retries + 1):
        try:
            qclient = get_client()
            try:
                await ensure_collection(qclient)
                async with MevzuatClient() as mevzuat_client:
                    count = await _seed_one_law(
                        mevzuat_client, embedder, qclient, kanun_kodu, kanun_adi,
                    )
                    if count > 0:
                        return (kanun_kodu, count, "ok")
                    last_err = "no_maddeler_parsed"
                    raise RuntimeError(last_err)
            finally:
                await qclient.close()
        except Exception as exc:
            last_err = f"{type(exc).__name__}:{exc!s}"[:140]
            log.warning(
                "seed_retry attempt=%d/%d kod=%s err=%s",
                attempt, max_retries, kanun_kodu, last_err,
            )
            if attempt < max_retries:
                await asyncio.sleep(delay)
                delay *= 2
    return (kanun_kodu, 0, f"failed:{last_err}")


async def main(only: list[str] | None) -> int:
    from retrieval.embedding import Embedder
    from retrieval.vector_store import get_client
    from scripts.seed_mevzuat import TARGET_LAWS

    print("=" * 70)
    print(" SEED RETRY — mevzuat-mcp rate-limit safe")
    print("=" * 70)

    qclient = get_client()
    try:
        existing = await _existing_kanun_kodlari(qclient)
    finally:
        await qclient.close()
    print(f"[*] Qdrant'ta mevcut kanun_kodu setleri: {sorted(existing) or '(boş)'}")

    target: list[tuple[str, str]] = list(TARGET_LAWS)
    if only:
        wanted = {x.strip().upper() for x in only}
        target = [(k, a) for (k, a) in target if k.upper() in wanted]

    # Zaten olanları skip et
    pending = [(k, a) for (k, a) in target if k not in existing]
    skipped = [k for (k, _a) in target if k in existing]
    print(f"[*] Skip (mevcut)   : {skipped}")
    print(f"[*] Eklenecek       : {[k for k, _ in pending]}")

    if not pending:
        print("[OK] Eklenecek yeni kanun yok.")
        return 0

    embedder = Embedder()
    # Embedder warm-up — ilk encode lazy
    print("[*] Embedder warming...")
    embedder.encode(["warmup"], return_colbert=False)

    results: list[tuple[str, int, str]] = []
    for kod, ad in pending:
        print(f"\n[→] {kod} ({ad})")
        res = await _seed_one(kod, ad, embedder)
        results.append(res)
        # Paket arası nezaket bekleme (MCP cache prep)
        await asyncio.sleep(3)

    # Rapor
    report_path = Path("data/seed_state/retry_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "skipped": skipped,
        "results": [{"kod": k, "madde_count": n, "status": s} for (k, n, s) in results],
        "total_added": sum(n for (_k, n, _s) in results if _s == "ok"),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    print("\n" + "=" * 70)
    print(" RAPOR")
    print("=" * 70)
    for k, n, s in results:
        flag = "✓" if s == "ok" else "✗"
        print(f"  {flag} {k:<10s} {n:>5d} madde  | {s}")
    print(f"\nToplam eklenen madde: {report['total_added']}")
    print(f"Rapor: {report_path}")
    return 0


def _preload_embedder_sync() -> None:
    """Windows + asyncio + torch CPU/CUDA lazy load = SIGSEGV. asyncio.run()
    öncesi main thread'de sync warmup — main.py:lifespan ile aynı mantık.
    """
    print("[*] Preload Embedder (sync, main thread)...", flush=True)
    from retrieval.embedding import Embedder
    Embedder().encode(["warmup"], return_colbert=False)
    print("[*] Embedder ready", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--only", default="", help="virgülle ayrılı kanun kodları (HMK,IYUK)")
    args = p.parse_args()
    only_list = [x for x in args.only.split(",") if x.strip()] or None
    _preload_embedder_sync()
    sys.exit(asyncio.run(main(only_list)))
