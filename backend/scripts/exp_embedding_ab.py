"""EMBEDDING A/B — 5 aday dense model × law-only koleksiyon × madde_recall@5 (2026-06-04).

"Ağır embedding swap" kararının ÖLÇÜM-ÖNCE adımı: 159K'yı kör re-embed etmeden, 7.293 law
chunk'ı her adayla law-only test koleksiyona embed edip benchmark madde_recall@5'i Mursit-Base'e
karşı kıyaslar. Kazanan model varsa tam re-embed değer; yoksa limit kanıtlanır.

Adaylar (hepsi yerel HF cache'te): Mursit-Base (kontrol), Mursit-Large, BGE-M3, mE5-large, gte.
Çalıştır (GPU env): EMBEDDING_DEVICE=cuda uv run python -m scripts.exp_embedding_ab
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

SRC = "adalet_mursit_hybrid"
BATCH = 64
TOPK = 5
# Windows GPU'da cuBLAS_STATUS_NOT_SUPPORTED yaşandı (2026-06-04) → CPU varsayılan (robust,
# bir kerelik ölçüm; cuda istenirse AB_DEVICE=cuda).
DEVICE = os.getenv("AB_DEVICE", "cpu")
OUT = Path("eval/runs/embedding_ab.json")

# (etiket, hf_path, query_prefix, doc_prefix). AB_MODELS env ile alt-küme seçilebilir.
_ALL = [
    ("mursit-base", "newmindai/Mursit-Base-TR-Retrieval", "", ""),
    ("mursit-large", "newmindai/Mursit-Large-TR-Retrieval", "", ""),
    ("bge-m3", "BAAI/bge-m3", "", ""),
    ("e5-large", "intfloat/multilingual-e5-large", "query: ", "passage: "),
    ("gte-base", "Alibaba-NLP/gte-multilingual-base", "", ""),
]
_sel = os.getenv("AB_MODELS", "")
CANDIDATES = [c for c in _ALL if c[0] in _sel.split(",")] if _sel else _ALL


def _load_law_chunks(client: QdrantClient) -> list[dict]:
    flt = models.Filter(must=[models.FieldCondition(key="doc_type", match=models.MatchValue(value="law"))])
    out, offset = [], None
    while True:
        pts, offset = client.scroll(SRC, scroll_filter=flt, limit=512, offset=offset,
                                    with_payload=True, with_vectors=False)
        for p in pts:
            pl = p.payload or {}
            t = pl.get("text", "")
            if t:
                out.append({"text": t, "kanun_kodu": pl.get("kanun_kodu"), "madde_no": pl.get("madde_no")})
        if offset is None:
            break
    return out


def _load_benchmark() -> list[dict]:
    cases = []
    for line in Path("data/eval_benchmark/benchmark_v2.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        exp_m = c.get("expected_madde_no") or []
        exp_k = c.get("expected_kanun") or []
        if exp_m and exp_k:
            cases.append({"soru": c.get("soru", ""), "domain": c.get("expected_domain"),
                          "kanun": {str(k) for k in exp_k}, "madde": {int(m) for m in exp_m if str(m).lstrip("-").isdigit()}})
    return cases


def _madde_recall(results, exp_kanun: set, exp_madde: set) -> float:
    for r in results:
        pl = r.payload or {}
        if str(pl.get("kanun_kodu")) in exp_kanun and pl.get("madde_no") in exp_madde:
            return 1.0
    return 0.0


def _eval_model(client, label, path, qpref, dpref, law, cases) -> dict:
    from sentence_transformers import SentenceTransformer
    print(f"\n[{label}] yukleniyor: {path} (device={DEVICE})", flush=True)
    model = SentenceTransformer(path, trust_remote_code=True, device=DEVICE)
    dim = model.get_sentence_embedding_dimension()
    col = f"ab_{label.replace('-', '_')}"
    client.recreate_collection(col, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
    # embed + upsert docs
    print(f"  embed {len(law)} law chunk (dim={dim})...", flush=True)
    for i in range(0, len(law), 256):
        batch = law[i:i + 256]
        vecs = model.encode([dpref + c["text"] for c in batch], batch_size=BATCH,
                            convert_to_numpy=True, show_progress_bar=False, normalize_embeddings=True)
        pts = [models.PointStruct(id=i + j, vector=v.tolist(),
                                  payload={"kanun_kodu": batch[j]["kanun_kodu"], "madde_no": batch[j]["madde_no"]})
               for j, v in enumerate(vecs)]
        client.upsert(col, points=pts)
    # benchmark
    print(f"  benchmark {len(cases)} vaka...", flush=True)
    by_dom = defaultdict(list)
    hits = 0
    for c in cases:
        qv = model.encode([qpref + c["soru"]], convert_to_numpy=True, normalize_embeddings=True)[0]
        res = client.query_points(col, query=qv.tolist(), limit=TOPK, with_payload=True).points
        r = _madde_recall(res, c["kanun"], c["madde"])
        hits += r
        by_dom[c["domain"]].append(r)
    client.delete_collection(col)
    del model
    if DEVICE == "cuda":
        import torch
        torch.cuda.empty_cache()
    overall = round(hits / len(cases), 4)
    per_dom = {d: round(sum(v) / len(v), 3) for d, v in sorted(by_dom.items())}
    return {"label": label, "dim": dim, "madde_recall@5": overall, "per_domain": per_dom}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = QdrantClient(url="http://localhost:6333", timeout=120)
    law = _load_law_chunks(client)
    _lim = int(os.getenv("LAW_LIMIT", "0"))  # sanity-test için law subsample (0=tümü)
    if _lim:
        law = law[:_lim]
    cases = _load_benchmark()
    print(f"law chunk: {len(law)} · benchmark vaka (madde'li): {len(cases)}", flush=True)
    results = []
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for label, path, qp, dp in CANDIDATES:
        try:
            r = _eval_model(client, label, path, qp, dp, law, cases)
            results.append(r)
            print(f"  ==> {label}: madde_recall@5 = {r['madde_recall@5']:.1%}", flush=True)
        except Exception as exc:
            print(f"  [{label}] HATA: {type(exc).__name__}: {exc}", flush=True)
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")  # incremental
    bar = "=" * 70
    print(f"\n{bar}\n  EMBEDDING A/B — madde_recall@5 (law-only, {len(cases)} vaka)\n{bar}")
    for r in sorted(results, key=lambda x: -x["madde_recall@5"]):
        print(f"  {r['label']:14s} dim={r['dim']:5d}  madde_recall@5={r['madde_recall@5']:.1%}")
    print(f"  {'-' * 66}")
    for r in sorted(results, key=lambda x: -x["madde_recall@5"]):
        print(f"  {r['label']:14s} {r['per_domain']}")
    print(bar)
    Path("eval/runs").mkdir(parents=True, exist_ok=True)
    Path("eval/runs/embedding_ab.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  -> eval/runs/embedding_ab.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
