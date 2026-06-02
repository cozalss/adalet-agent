"""Faz-4 adım 2 — GERÇEK pozitif belgelerden KONUŞMA-DİLİ soru sentezle (InPars deseni).

Datasetin resmî 'catchword' sorgusu ("Mecurun Erken Tahliyesi – m.260") vatandaşın
diline benzemez → projenin eş-anlam sorununu ("depozito" vs "güvence bedeli") çözmez.
Bu script her GERÇEK pozitif karar/madde için yerel Qwen'e few-shot verip kolokyal
vatandaş sorusu ("kiradan erken çıktım, depozitomu vermiyorlar") ürettirir.

KIRMIZI ÇİZGİ: LLM yalnız SORU üretir; pozitif kaynak GERÇEK karardır (uydurma yok).
İki kalite kapısı:
  1. clean_synth_query — jargon/kopya/uzunluk eler (saf, _core).
  2. consistency (round-trip) — sentez soru, embedder altında KENDİ pozitifini N
     çeldirici arasında top_k'da getiriyor mu? Getirmiyorsa muğlak → ELE. Qdrant
     GEREKMEZ (dataset corpus'undan örneklenen çeldiricilerle kendi-kendine yeter).

Üretir: data/reranker/synth_pairs.jsonl  ({query_id, query, pos_id, pos_text, domain, source='synth'})

Kullanım (yerel LLM gerekir):
  cd backend && LLM_MODE=llamacpp_server uv run python -m scripts.reranker.synth_queries [--limit N] [--no-roundtrip]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import sys
from dataclasses import asdict
from pathlib import Path

from agents.llm import ChatMessage, get_llm

# Windows: pyarrow'u torch'tan ÖNCE yükle (embedder + datasets segfault guard).
# `core` first-party'de alfabetik olarak embedder'lardan önce; torch lazy yüklendiği
# için bu import modül yükünde çalışıp guard'ı kurar.
from core import native_preload  # noqa: F401
from scripts.reranker._core import (
    QAPair,
    build_synth_messages,
    clean_synth_query,
    roundtrip_keep,
    tag_domain,
)

_OUT_DIR = Path("data/reranker")
_SYNTH_TEMPERATURE = 0.6  # çeşitlilik + tutarlılık dengesi (yüksekte Qwen bozuluyor)
_SYNTH_MAX_TOKENS = 120   # bir soru kısadır


def _load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _unique_positives(pairs: list[dict]) -> list[tuple[str, str]]:
    """(pos_id, pos_text) benzersizleri — aynı belgeye tekrar soru üretme."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for p in pairs:
        if p["pos_id"] not in seen:
            seen.add(p["pos_id"])
            out.append((p["pos_id"], p["pos_text"]))
    return out


async def synth_one(llm, pos_text: str) -> str | None:
    """Tek pozitif belge → temizlenmiş konuşma-dili soru (veya None)."""
    messages = [ChatMessage(role=m["role"], content=m["content"])
                for m in build_synth_messages(pos_text)]
    resp = await llm.chat(messages, temperature=_SYNTH_TEMPERATURE, max_tokens=_SYNTH_MAX_TOKENS)
    return clean_synth_query(resp.content, pos_text)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def consistency_keep(embedder, synth_q: str, pos_id: str, pos_text: str,
                     distractors: list[tuple[str, str]], top_k: int) -> bool:
    """Round-trip: sentez soru, pozitifini çeldiriciler arasında top_k'da getiriyor mu?

    Embedder ile [pos + çeldiriciler] dense vektörlerini sorguya göre sırala; pozitif
    id'si ilk top_k'da ise TUT (_core.roundtrip_keep). Qdrant değil, dataset corpus'u.
    """
    docs = [(pos_id, pos_text), *distractors]
    out = embedder.encode([synth_q] + [t for _, t in docs])
    qv, dvs = out.dense[0], out.dense[1:]
    ranked = sorted(
        ((doc_id, _cosine(qv, dv)) for (doc_id, _), dv in zip(docs, dvs, strict=True)),
        key=lambda x: x[1], reverse=True,
    )
    return roundtrip_keep(pos_id, [doc_id for doc_id, _ in ranked], top_k=top_k)


async def run(limit: int | None, do_roundtrip: bool, n_distractors: int, top_k: int) -> None:
    pairs = _load_jsonl(_OUT_DIR / "pairs.jsonl")
    positives = _unique_positives(pairs)
    if limit:
        positives = positives[:limit]
    corpus = _load_jsonl(_OUT_DIR / "corpus.jsonl")
    rng = random.Random(42)

    if os.getenv("LLM_MODE", "mock") == "mock":
        print("[!] LLM_MODE=mock — sentez gerçek Qwen ister; çıktı anlamlı olmaz. "
              "LLM_MODE=llamacpp(_server) ile çalıştır.", flush=True)

    llm = get_llm()
    embedder = None
    if do_roundtrip:
        from retrieval.embedding import get_embedder
        embedder = get_embedder()

    kept: list[QAPair] = []
    for i, (pos_id, pos_text) in enumerate(positives):
        q = await synth_one(llm, pos_text)
        if not q:
            continue
        if embedder is not None:
            pool = [(c["id"], c["text"]) for c in corpus if c["id"] != pos_id]
            distractors = rng.sample(pool, min(n_distractors, len(pool)))
            if not consistency_keep(embedder, q, pos_id, pos_text, distractors, top_k):
                continue
        kept.append(QAPair(
            query_id=f"synth-{i}", query=q, pos_id=pos_id, pos_text=pos_text,
            domain=tag_domain(pos_text[:400]), source="synth",
        ))
        if (i + 1) % 25 == 0:
            print(f"    {i+1}/{len(positives)} işlendi, {len(kept)} kabul", flush=True)

    out_path = _OUT_DIR / "synth_pairs.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for p in kept:
            f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
    rate = len(kept) / len(positives) if positives else 0.0
    print(f"[+] {len(kept)}/{len(positives)} konuşma-dili soru kabul ({rate:.0%}) -> {out_path}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Konuşma-dili soru sentezi (Qwen few-shot)")
    parser.add_argument("--limit", type=int, default=None, help="En fazla N pozitif belge")
    parser.add_argument("--no-roundtrip", action="store_true",
                        help="Embedder consistency filtresini atla (yalnız leksik temizleme)")
    parser.add_argument("--distractors", type=int, default=20,
                        help="Round-trip çeldirici sayısı (varsayılan 20)")
    parser.add_argument("--top-k", type=int, default=10, help="Round-trip top_k eşiği")
    args = parser.parse_args()
    asyncio.run(run(args.limit, not args.no_roundtrip, args.distractors, args.top_k))


if __name__ == "__main__":
    main()
