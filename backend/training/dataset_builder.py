"""LoRA dataset builder — Qdrant'tan (anchor, positive, negative) triplet üret.

Türkçe hukuk corpus için pozitif örnekler:
  - (Yargıtay kararı snippet, kararda atıfta bulunulan madde metni)
    Regex'le madde referansı bulunur (graph_rag._LAW_ID_RE), madde Qdrant'tan
    fetch edilir → pozitif çift.
  - (Soru benzeri parafraz, ilgili madde) — LLM ile parafraz üretimi
    opsiyonel (LoRA train öncesi offline batch). Bu modül ŞU AN sadece
    karar→madde citation eşleşmelerini kullanır.

Hard-negative mining:
  - Aynı domain içinde rastgele BAŞKA madde (semantically close ama yanlış)
  - Düşük rank ile alır → BM25 close-but-wrong en faydalı

JSONL şema (her satır):
    {"anchor": "<karar snippet 600 char>",
     "positive": "<madde metni>",
     "negative": "<aynı domain başka madde>",
     "meta": {"law_id": "TKHK:11", "case_id": "Yargitay:2019/1234"}}

Çalıştır:
    uv run python -m training.dataset_builder --out data/lora/train.jsonl --limit 5000

Default-safe: Qdrant boşsa modül çalışır ama 0 örnek yazar (early return).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import structlog

# UTF-8 zorla (Windows cp1254)
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

log = structlog.get_logger()

DEFAULT_OUT = Path(os.getenv("LORA_DATASET_PATH", "data/lora/train.jsonl"))
DEFAULT_LIMIT = int(os.getenv("LORA_DATASET_LIMIT", "5000"))
HARD_NEG_PER_POS = int(os.getenv("LORA_HARD_NEG_K", "1"))
ANCHOR_MAX_CHARS = 600
POS_MAX_CHARS = 600


@dataclass(slots=True)
class TripletExample:
    anchor: str
    positive: str
    negative: str
    meta: dict


# --------------------------------------------------------------------------
#  Mining
# --------------------------------------------------------------------------

async def build_triplets(
    out_path: Path = DEFAULT_OUT,
    limit: int = DEFAULT_LIMIT,
    seed: int = 42,
) -> int:
    """Qdrant'tan triplet üret, JSONL'e yaz, sayıyı döndür."""
    from retrieval.graph_rag import extract_seed_ids
    from retrieval.vector_store import COLLECTION_NAME, get_client

    rng = random.Random(seed)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    client = get_client()
    n_written = 0
    try:
        # Collection var mı?
        cols = await client.get_collections()
        if not any(c.name == COLLECTION_NAME for c in cols.collections):
            log.warning("dataset_no_collection", name=COLLECTION_NAME)
            return 0

        # Önce: tüm law payload'larını cache'le (kanun, madde) → text eşlemesi
        law_index, domain_index = await _scan_law_index(client)
        if not law_index:
            log.warning("dataset_no_laws_in_qdrant")
            return 0

        # Karar dökümanları scroll → atıfları çıkar → triplet
        n_cases_scanned = 0
        with out_path.open("w", encoding="utf-8") as fh:
            offset = None
            while n_written < limit:
                points, offset = await client.scroll(
                    collection_name=COLLECTION_NAME,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                if not points:
                    break

                for p in points:
                    payload = p.payload or {}
                    if payload.get("doc_type") != "case" and payload.get("source") not in {
                        "anayasa", "yargitay", "danistay", "bedesten",
                    }:
                        continue
                    text = (payload.get("text") or "").strip()
                    if len(text) < 100:
                        continue

                    n_cases_scanned += 1
                    domain = payload.get("domain", "unknown")
                    seeds = extract_seed_ids([text[:3000]])
                    case_id = (
                        f"{payload.get('court', 'Mahkeme')}:"
                        f"{payload.get('esas_no', '?')}/{payload.get('karar_no', '?')}"
                    )

                    for sid in seeds:
                        if not sid.startswith("law:"):
                            continue
                        parts = sid.split(":")
                        if len(parts) != 3:
                            continue
                        law_key = (parts[1], int(parts[2]))
                        pos_text = law_index.get(law_key)
                        if not pos_text:
                            continue

                        neg_text = _sample_negative(law_index, domain_index, domain, law_key, rng)
                        if not neg_text:
                            continue

                        ex = TripletExample(
                            anchor=text[:ANCHOR_MAX_CHARS],
                            positive=pos_text[:POS_MAX_CHARS],
                            negative=neg_text[:POS_MAX_CHARS],
                            meta={
                                "law_id": f"{law_key[0]}:{law_key[1]}",
                                "case_id": case_id,
                                "domain": domain,
                            },
                        )
                        fh.write(json.dumps(ex.__dict__, ensure_ascii=False) + "\n")
                        n_written += 1
                        if n_written >= limit:
                            break

                    if n_written >= limit:
                        break

                if offset is None:
                    break

        log.info(
            "dataset_done",
            n_written=n_written,
            n_cases_scanned=n_cases_scanned,
            out=str(out_path),
        )
        return n_written
    finally:
        await client.close()


async def _scan_law_index(
    client,
) -> tuple[dict[tuple[str, int], str], dict[str, list[tuple[str, int]]]]:
    """Qdrant'tan tüm law payload'larını çek, (kanun, madde) → text + domain index."""
    from retrieval.vector_store import COLLECTION_NAME

    law_text: dict[tuple[str, int], str] = {}
    domain_buckets: dict[str, list[tuple[str, int]]] = {}

    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=COLLECTION_NAME,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break
        for p in points:
            payload = p.payload or {}
            if payload.get("doc_type") != "law" and payload.get("source") != "mevzuat":
                continue
            kanun = payload.get("kanun_kodu")
            madde = payload.get("madde_no")
            text = (payload.get("text") or "").strip()
            if not (kanun and madde and text):
                continue
            try:
                madde_int = int(madde)
            except (TypeError, ValueError):
                continue
            key = (str(kanun).upper(), madde_int)
            # İlk gelen kazanır (chunk'lar arasında ilk parça genelde en iyi tarif)
            if key not in law_text:
                law_text[key] = text
                domain = payload.get("domain", "unknown")
                domain_buckets.setdefault(domain, []).append(key)
        if offset is None:
            break

    return law_text, domain_buckets


def _sample_negative(
    law_index: dict[tuple[str, int], str],
    domain_index: dict[str, list[tuple[str, int]]],
    domain: str,
    positive_key: tuple[str, int],
    rng: random.Random,
    max_tries: int = 8,
) -> str | None:
    """Aynı domain içinden farklı bir madde seç. Yoksa rastgele global madde."""
    candidates = domain_index.get(domain, [])
    if len(candidates) < 2:
        # Domain'de sadece bir madde varsa → global pool
        all_keys = list(law_index.keys())
        candidates = all_keys

    for _ in range(max_tries):
        cand = rng.choice(candidates)
        if cand != positive_key and cand in law_index:
            return law_index[cand]
    return None


# --------------------------------------------------------------------------
#  CLI
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="BGE-M3 LoRA dataset builder")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output JSONL path")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max triplets")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for negatives")
    args = parser.parse_args()

    n = asyncio.run(build_triplets(out_path=args.out, limit=args.limit, seed=args.seed))
    print(f"[OK] {n} triplet yazildi: {args.out}")
    return 0 if n > 0 else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ("TripletExample", "build_triplets")
