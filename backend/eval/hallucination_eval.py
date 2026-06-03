"""Halüsinasyon kalkanı — detektör precision/recall ölçüm harness'ı.

Etiketli gold-set (data/eval_benchmark/hallucination_gold.jsonl) üzerinde tüm
içerik-risk detektörlerini koşar; detektör-başına + genel precision/recall/F1 +
temiz cevaplarda **veto false-positive** oranını (iyi cevabı yanlışlıkla reddetme)
raporlar. Saf çekirdek (detect_types / score_gold) LLM'siz test edilebilir.

Gold satır: {"id","answer","types":[<halüsinasyon türleri>],"is_clean":bool}.

Kullanım:
    uv run python -m eval.hallucination_eval --gold data/eval_benchmark/hallucination_gold.jsonl
    uv run python -m eval.hallucination_eval --gold <path> --out eval/runs/hallu.json
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from agents.risk_guard import (
    fabricated_citation_claims,
    fabricated_law_names,
    negative_eligibility_claims,
    verify_risk_veto,
)
from eval.answer_risk import (
    implausible_article_numbers,
    unsourced_legal_claims,
)

# tür → detektör (saf fonksiyon: str → list[str]). Bunlar gold etiketleriyle eşleşir.
_DETECTORS = {
    "fabricated_law": fabricated_law_names,
    "negative_eligibility": negative_eligibility_claims,
    "fabricated_citation": fabricated_citation_claims,
    "implausible_article": implausible_article_numbers,
    "unsourced_claim": unsourced_legal_claims,
}


def detect_types(answer: str) -> set[str]:
    """Cevapta fire eden tüm risk türlerinin kümesi."""
    return {t for t, fn in _DETECTORS.items() if fn(answer)}


@dataclass(frozen=True)
class TypeMetric:
    type: str
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return round(self.tp / d, 3) if d else 1.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return round(self.tp / d, 3) if d else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return round(2 * p * r / (p + r), 3) if (p + r) else 0.0

    def to_dict(self) -> dict:
        return asdict(self) | {"precision": self.precision, "recall": self.recall, "f1": self.f1}


def score_gold(rows: list[dict]) -> dict:
    """Gold satırları → detektör-başına + genel metrikler + veto-FP. Saf, LLM'siz."""
    per_type: dict[str, TypeMetric] = {}
    tot_tp = tot_fp = tot_fn = 0
    for t in _DETECTORS:
        tp = fp = fn = 0
        for r in rows:
            predicted = t in detect_types(r["answer"])
            actual = t in r.get("types", [])
            tp += int(predicted and actual)
            fp += int(predicted and not actual)
            fn += int((not predicted) and actual)
        per_type[t] = TypeMetric(t, tp, fp, fn)
        tot_tp += tp
        tot_fp += fp
        tot_fn += fn

    clean = [r for r in rows if r.get("is_clean")]
    bad = [r for r in rows if not r.get("is_clean")]
    # KRİTİK: temiz cevap veto'yu tetiklememeli (iyi cevabı reddetme = kötü).
    veto_fp = sum(1 for r in clean if verify_risk_veto(r["answer"])[0])
    # Kötü cevabın EN AZ BİR beklenen türü yakalandı mı (halüsinasyon yakalama).
    caught = sum(1 for r in bad if detect_types(r["answer"]) & set(r.get("types", [])))

    return {
        "n": len(rows),
        "n_clean": len(clean),
        "n_bad": len(bad),
        "micro_precision": round(tot_tp / (tot_tp + tot_fp), 3) if (tot_tp + tot_fp) else 1.0,
        "micro_recall": round(tot_tp / (tot_tp + tot_fn), 3) if (tot_tp + tot_fn) else 1.0,
        "veto_false_positives": veto_fp,
        "veto_fp_rate": round(veto_fp / len(clean), 3) if clean else 0.0,
        "hallucination_recall": round(caught / len(bad), 3) if bad else 1.0,
        # Ham sayımlar (güven aralığı hesabı için — eval/stats.wilson_interval):
        "caught": caught,
        "tot_tp": tot_tp,
        "tot_fp": tot_fp,
        "per_type": {t: m.to_dict() for t, m in per_type.items()},
    }


def load_gold(path: str) -> list[dict]:
    """JSONL gold-set yükle (boş satırlar atlanır)."""
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def print_scorecard(s: dict) -> None:
    bar = "=" * 64
    print(f"\n{bar}\n  HALÜSİNASYON KALKANI — {s['n']} cevap ({s['n_clean']} temiz / {s['n_bad']} riskli)\n{bar}")
    print(f"  micro  precision={s['micro_precision']}  recall={s['micro_recall']}")
    print(f"  halüsinasyon yakalama (recall) = {s['hallucination_recall']:.0%}")
    mark = "✅" if s["veto_false_positives"] == 0 else "❌"
    print(f"  {mark} VETO false-positive (temiz cevap reddi) = "
          f"{s['veto_false_positives']}/{s['n_clean']}  (hedef: 0)")
    print(f"  {'-' * 62}")
    for t, m in s["per_type"].items():
        print(f"  {t:<22} P={m['precision']:<5} R={m['recall']:<5} F1={m['f1']:<5} "
              f"(tp={m['tp']} fp={m['fp']} fn={m['fn']})")
    print(bar)


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Halüsinasyon kalkanı ölçüm harness'ı")
    parser.add_argument("--gold", default="data/eval_benchmark/hallucination_gold.jsonl")
    parser.add_argument("--out", default=None, help="Scorecard JSON çıktısı")
    args = parser.parse_args()

    scorecard = score_gold(load_gold(args.gold))
    print_scorecard(scorecard)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(scorecard, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Sonuç -> {out}")
    # veto false-positive varsa fail (iyi cevap reddedilmemeli — regresyon kapısı).
    sys.exit(1 if scorecard["veto_false_positives"] > 0 else 0)
