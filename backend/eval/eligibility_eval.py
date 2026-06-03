"""Süre-uygunluk FABRİKE-eşik detektörü değerlendirmesi (yarışma kanıt-tablosu).

`agents.risk_guard.fabricated_eligibility_threshold`'ü adversarial gold set
(`data/eval_benchmark/eligibility_adversarial.jsonl`) üzerinde ölçer:
- FABRİKE eşikleri ('5 yıldan az tazminat verilmez' = kaynakta olmayan uydurma) YAKALAR mı?
- DOĞRU eşikleri ('1 yılın altında kıdem yok' = kaynakta var) YANLIŞLIKLA işaretler mi (false-positive)?

'Sıfır halüsinasyon' iddiasının jüriye gösterilebilir kanıtı: deterministik (prompt değil),
kaynak-temelli, ölçülü. Saf çekirdek (LLM yok) → test edilebilir.

Çalıştır: cd backend && uv run python -m eval.eligibility_eval
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.risk_guard import fabricated_eligibility_threshold

_GOLD = (
    Path(__file__).resolve().parent.parent
    / "data" / "eval_benchmark" / "eligibility_adversarial.jsonl"
)


def load_gold(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else _GOLD
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def evaluate(cases: list[dict]) -> dict:
    """FABRİKE = pozitif sınıf. precision/recall/F1 + her vaka doğru mu."""
    tp = fp = fn = tn = 0
    rows: list[dict] = []
    for c in cases:
        flagged = bool(fabricated_eligibility_threshold(c["answer"], c.get("sources", [])))
        is_fab = c["label"] == "fabricated"
        if is_fab and flagged:
            tp += 1
        elif is_fab and not flagged:
            fn += 1
        elif not is_fab and flagged:
            fp += 1
        else:
            tn += 1
        rows.append({"id": c["id"], "label": c["label"], "flagged": flagged,
                     "correct": is_fab == flagged})
    n = len(cases) or 1
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "n": len(cases), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(f1, 4), "accuracy": round((tp + tn) / n, 4),
        "rows": rows,
    }


def main() -> dict:
    res = evaluate(load_gold())
    print(f"FABRİKE-eşik detektörü — {res['n']} adversarial vaka")
    print(f"  precision={res['precision']} recall={res['recall']} "
          f"f1={res['f1']} accuracy={res['accuracy']}")
    print(f"  TP={res['tp']} FP={res['fp']} FN={res['fn']} TN={res['tn']}")
    wrong = [r for r in res["rows"] if not r["correct"]]
    if wrong:
        print("  YANLIŞLAR:")
        for r in wrong:
            print(f"    {r['id']} ({r['label']}) flagged={r['flagged']}")
    return res


if __name__ == "__main__":
    main()
