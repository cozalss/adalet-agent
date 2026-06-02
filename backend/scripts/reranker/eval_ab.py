"""Faz-4 A/B — base vs fine-tuned reranker'ı held-out val üzerinde karşılaştır.

data/reranker/val.jsonl ({query, passage, label}) üzerinde İKİ reranker'ı skorlar ve
sorgu-başına pairwise doğruluğu (pozitif > negatif oranı) + pozitif/negatif ortalama
ayrımını raporlar. Fine-tune kazancını eşikten BAĞIMSIZ, doğrudan ölçer (Qdrant gerekmez).

Kullanım:
  cd backend && uv run python -m scripts.reranker.eval_ab
  uv run python -m scripts.reranker.eval_ab --base BAAI/bge-reranker-v2-m3 --new models/reranker-tr-legal
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows: pyarrow'u torch'tan ÖNCE yükle (segfault guard).
from core import native_preload  # noqa: F401
from scripts.reranker._core import rerank_pairwise_accuracy

_VAL = Path("data/reranker/val.jsonl")
_DEFAULT_BASE = "BAAI/bge-reranker-v2-m3"
_DEFAULT_NEW = "models/reranker-tr-legal"


def _score(model_name: str, rows: list[dict], max_length: int) -> dict:
    """Bir reranker'la tüm (query, passage) çiftlerini skorla → pairwise metrik."""
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(model_name, max_length=max_length)
    scores = model.predict([(r["query"], r["passage"]) for r in rows])
    scored = [(r["query"], float(s), float(r["label"]))
              for r, s in zip(rows, scores, strict=True)]
    return rerank_pairwise_accuracy(scored)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Reranker A/B (base vs fine-tuned)")
    parser.add_argument("--base", default=_DEFAULT_BASE)
    parser.add_argument("--new", default=_DEFAULT_NEW)
    parser.add_argument("--val", default=str(_VAL))
    parser.add_argument("--max-length", type=int, default=320)
    args = parser.parse_args()

    val_path = Path(args.val)
    if not val_path.exists():
        raise SystemExit(f"{val_path} yok — önce mine_negatives çalıştır.")
    rows = [json.loads(line) for line in val_path.open(encoding="utf-8") if line.strip()]

    print(f"[*] {len(rows)} val çifti üzerinde A/B...", flush=True)
    base = _score(args.base, rows, args.max_length)
    new = _score(args.new, rows, args.max_length)

    bar = "=" * 64
    print(f"\n{bar}\n  RERANKER A/B — {len(rows)} held-out çift ({base['n_comparisons']} pozitif×negatif)\n{bar}")
    print(f"  {'metrik':<22}{'BASE':>12}{'NEW (fine-tune)':>18}")
    print(f"  {'-'*58}")
    print(f"  {'pairwise accuracy':<22}{base['pairwise_accuracy']:>12.4f}{new['pairwise_accuracy']:>18.4f}")
    print(f"  {'ort. pozitif skor':<22}{base['mean_pos']:>12.4f}{new['mean_pos']:>18.4f}")
    print(f"  {'ort. negatif skor':<22}{base['mean_neg']:>12.4f}{new['mean_neg']:>18.4f}")
    base_gap = base["mean_pos"] - base["mean_neg"]
    new_gap = new["mean_pos"] - new["mean_neg"]
    print(f"  {'ayrım (poz-neg)':<22}{base_gap:>12.4f}{new_gap:>18.4f}")
    delta = new["pairwise_accuracy"] - base["pairwise_accuracy"]
    verdict = "✓ fine-tune İYİLEŞTİRDİ" if delta > 0 else (
        "≈ fark yok" if abs(delta) < 1e-4 else "✗ fine-tune kötüleştirdi")
    print(f"  {'-'*58}\n  Δ pairwise accuracy = {delta:+.4f}  {verdict}\n{bar}")


if __name__ == "__main__":
    main()
