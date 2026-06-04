"""RERANKER A/B — genel bge-reranker vs TR-hukuk-tuned reranker (2026-06-04).

"Yanlış madde" residüeli embedding değil RANKING sorunu (embedding A/B kanıtladı).
Bu harness mevcut corpus'u (mursit_hybrid, RE-EMBED YOK) kullanır: her benchmark sorgusu →
Mursit dense top-20 law aday → 3 sıralama ile madde_recall@5:
  - dense (rerank yok, kontrol)
  - bge-reranker-v2-m3 (production, genel)
  - reranker-tr-legal (yerel, 7.168 TR-hukuk örneğiyle fine-tune — KULLANILMIYOR)

TR-hukuk reranker kazanırsa → production reranker'ı değiştir (ucuz config, re-embed yok).
Çalıştır: AB_DEVICE=cpu uv run python -m scripts.exp_reranker_ab
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from qdrant_client import QdrantClient, models

import core.native_preload  # noqa: F401

COL = "adalet_mursit_hybrid"
EMB = "newmindai/Mursit-Base-TR-Retrieval"
RERANKERS = {
    "bge-genel": "BAAI/bge-reranker-v2-m3",
    "tr-legal": str(Path(__file__).parent.parent / "models" / "reranker-tr-legal"),
}
CAND = 20   # dense aday havuzu
TOPK = 5
DEVICE = os.getenv("AB_DEVICE", "cpu")


def _load_benchmark() -> list[dict]:
    cases = []
    for line in Path("data/eval_benchmark/benchmark_v2.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        exp_m = c.get("expected_madde_no") or []
        exp_k = c.get("expected_kanun") or []
        if exp_m and exp_k:
            cases.append({
                "soru": c.get("soru", ""), "domain": c.get("expected_domain"),
                "kanun": {str(k) for k in exp_k},
                "madde": {int(m) for m in exp_m if str(m).lstrip("-").isdigit()},
            })
    return cases


def _hit(cands: list[dict], exp_k: set, exp_m: set, k: int) -> float:
    for c in cands[:k]:
        if str(c.get("kanun_kodu")) in exp_k and c.get("madde_no") in exp_m:
            return 1.0
    return 0.0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from sentence_transformers import CrossEncoder, SentenceTransformer

    client = QdrantClient(url="http://localhost:6333", timeout=120)
    cases = _load_benchmark()
    print(f"benchmark: {len(cases)} vaka · device={DEVICE}", flush=True)

    # 1) Her sorgu için Mursit dense top-CAND law aday çek (rerank-öncesi)
    print(f"[1] Mursit TOPLU query embed ({len(cases)})...", flush=True)
    emb = SentenceTransformer(EMB, trust_remote_code=True, device=DEVICE)
    qvecs = emb.encode([c["soru"] for c in cases], batch_size=32,
                       convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
    del emb
    print(f"[1b] dense top-{CAND} law aday çekiliyor...", flush=True)
    law_filter = models.Filter(must=[models.FieldCondition(key="doc_type", match=models.MatchValue(value="law"))])
    per_case_cands = []
    for i, qv in enumerate(qvecs):
        res = client.query_points(COL, query=qv.tolist(), using="dense", query_filter=law_filter,
                                  limit=CAND, with_payload=True).points
        per_case_cands.append([{"text": (p.payload or {}).get("text", ""),
                                "kanun_kodu": (p.payload or {}).get("kanun_kodu"),
                                "madde_no": (p.payload or {}).get("madde_no")} for p in res])
        if (i + 1) % 50 == 0:
            print(f"    ...{i + 1}/{len(cases)} aday çekildi", flush=True)

    # 2) Kontrol: dense (rerank yok) madde_recall@5
    results = {}
    dom_acc = defaultdict(lambda: defaultdict(list))
    dense_hits = sum(_hit(per_case_cands[i], c["kanun"], c["madde"], TOPK) for i, c in enumerate(cases))
    results["dense (rerank yok)"] = round(dense_hits / len(cases), 4)
    for i, c in enumerate(cases):
        dom_acc["dense"][c["domain"]].append(_hit(per_case_cands[i], c["kanun"], c["madde"], TOPK))

    # 3) Her reranker ile yeniden-sırala
    for label, path in RERANKERS.items():
        print(f"[2] reranker: {label} ({path})...", flush=True)
        try:
            ce = CrossEncoder(path, device=DEVICE, max_length=320, trust_remote_code=True)
        except Exception as exc:
            print(f"  [{label}] yüklenemedi: {type(exc).__name__}: {exc}", flush=True)
            continue
        hits = 0
        for i, c in enumerate(cases):
            cands = per_case_cands[i]
            if not cands:
                continue
            pairs = [(c["soru"], x["text"]) for x in cands]
            scores = ce.predict(pairs, convert_to_numpy=True, show_progress_bar=False)
            order = sorted(range(len(cands)), key=lambda j: -scores[j])
            reranked = [cands[j] for j in order]
            h = _hit(reranked, c["kanun"], c["madde"], TOPK)
            hits += h
            dom_acc[label][c["domain"]].append(h)
        results[label] = round(hits / len(cases), 4)
        del ce
        print(f"  ==> {label}: madde_recall@5 = {results[label]:.1%}", flush=True)
        Path("eval/runs").mkdir(parents=True, exist_ok=True)
        Path("eval/runs/reranker_ab.json").write_text(
            json.dumps({"results": results, "per_domain": {k: {d: round(sum(v)/len(v), 3) for d, v in dd.items()}
                        for k, dd in dom_acc.items()}}, ensure_ascii=False, indent=2), encoding="utf-8")

    bar = "=" * 60
    print(f"\n{bar}\n  RERANKER A/B — madde_recall@5 ({len(cases)} vaka, top-{CAND} aday)\n{bar}")
    base = results.get("dense (rerank yok)", 0)
    for k, v in sorted(results.items(), key=lambda x: -x[1]):
        diff = f"  ({(v-base)*100:+.1f}pp vs dense)" if k != "dense (rerank yok)" else "  (kontrol)"
        print(f"  {k:22s} {v:.1%}{diff}")
    print(bar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
