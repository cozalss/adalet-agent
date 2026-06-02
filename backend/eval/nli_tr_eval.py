"""NLI-TR ölçüm harness'ı — mDeBERTa'nın Türkçe yanlış-pozitif çelişki oranı (Faz-3).

Bilinen sorun (verifier/nli.py docstring + kalibrasyon notları): mDeBERTa XNLI
Türkçe hukuk paraphrase'lerinde **çok sıkı** — entailment/neutral çiftleri yanlışlıkla
`contradiction` sayıp verify'da DOĞRU cevabı veto edebilir (yanlış-pozitif). Faz-1
halüsinasyon harness'ı deseniyle bunu KANITLA + ÖLÇ: etiketli TR NLI gold-set üzerinde
3-sınıf doğruluk + sınıf-başına P/R/F1 + **veto eşiğinde yanlış-pozitif çelişki oranı**.

Gold satır: {"id","premise","hypothesis","label"} — label ∈ {entailment, neutral,
contradiction}. NLI çağrısı: verify(claim=hypothesis, evidence=premise) (modelin
beklediği premise→hypothesis sırası nli.py'de premise=evidence ilk argüman).

Veri SENTETİK + dilbilimsel: çiftlerin entail/çelişki/neutral İLİŞKİSİ açık seçik
kurgulandı; bireysel ifadelerin hukuki doğruluğu ölçümün konusu DEĞİL (model fine-tune
EDİLMEZ — yalnız davranış ölçülür). CLAUDE.md §1: kullanıcıya sunulan uydurma referans yok.

Saf çekirdek (score_predictions) model GEREKMEZ → birim-test edilebilir. NLI yolu
opsiyonel (model ~280MB, main thread'de preload — Windows+torch segfault guard).

Kullanım:
    uv run python -m eval.nli_tr_eval                          # model yükler, ölçer
    uv run python -m eval.nli_tr_eval --out eval/runs/nli_tr.json
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# Production veto eşiği — verify bu eşikle is_contradicted veto'su uygular.
from agents.config import NLI_CONTRADICTION_THRESHOLD

LABELS = ("entailment", "neutral", "contradiction")
GOLD_PATH = Path(__file__).parent.parent / "data" / "eval_benchmark" / "nli_tr_gold.jsonl"
# Çelişki eşik taraması — production NLI_CONTRADICTION_THRESHOLD (0.70) dahil.
_SWEEP_THRESHOLDS = (0.40, 0.50, 0.60, 0.70, 0.80, 0.90)


@dataclass(frozen=True)
class LabelMetric:
    """Tek bir NLI sınıfı için karışıklık sayıları (one-vs-rest)."""

    label: str
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
        return asdict(self) | {
            "precision": self.precision, "recall": self.recall, "f1": self.f1,
        }


def score_predictions(gold: list[str], pred: list[str]) -> dict:
    """argmax tahminleri vs gold → 3-sınıf doğruluk + sınıf P/R/F1 + çelişki yanlış-pozitif.

    Saf — model GEREKMEZ (tahmin listeleri verilir). KRİTİK metrik:
    `contra_false_positive_rate` = entailment/neutral gold'larında YANLIŞLIKLA
    contradiction tahmini oranı (verify'da iyi cevabı veto eder → Faz-3 sorunu).
    """
    if len(gold) != len(pred):
        raise ValueError(f"gold ({len(gold)}) ile pred ({len(pred)}) uzunluğu farklı")

    per_label: dict[str, LabelMetric] = {}
    for lab in LABELS:
        tp = sum(1 for g, p in zip(gold, pred, strict=True) if g == lab and p == lab)
        fp = sum(1 for g, p in zip(gold, pred, strict=True) if g != lab and p == lab)
        fn = sum(1 for g, p in zip(gold, pred, strict=True) if g == lab and p != lab)
        per_label[lab] = LabelMetric(lab, tp, fp, fn)

    correct = sum(1 for g, p in zip(gold, pred, strict=True) if g == p)
    non_contra = [g for g in gold if g != "contradiction"]
    contra_fp = sum(
        1 for g, p in zip(gold, pred, strict=True)
        if g != "contradiction" and p == "contradiction"
    )
    n_contra = gold.count("contradiction")
    contra_caught = sum(
        1 for g, p in zip(gold, pred, strict=True)
        if g == "contradiction" and p == "contradiction"
    )
    return {
        "n": len(gold),
        "accuracy": round(correct / len(gold), 3) if gold else 0.0,
        # Faz-3 ANA metriği — düşük olmalı (iyi cevabı veto etmemeli).
        "contra_false_positive_rate": round(contra_fp / len(non_contra), 3)
        if non_contra else 0.0,
        "contra_false_positives": contra_fp,
        "n_non_contradiction": len(non_contra),
        "contradiction_recall": round(contra_caught / n_contra, 3) if n_contra else 1.0,
        "n_contradiction": n_contra,
        "per_label": {lab: m.to_dict() for lab, m in per_label.items()},
    }


def threshold_sweep(
    gold: list[str], contra_scores: list[float],
    thresholds: tuple[float, ...] = _SWEEP_THRESHOLDS,
) -> list[dict]:
    """Çelişki eşiği taraması: yakalama (recall) vs entailment/neutral'a yanlış-veto.

    Production veto `is_contradicted(con >= threshold)`. Her eşik için: gerçek
    çelişkilerin ne kadarı yakalandı + kaç doğru çift (non-contra) yanlışlıkla
    veto edildi. Eşik ↑ → yanlış-veto ↓ ama yakalama da ↓ (ödünleşim görünür).
    """
    rows: list[dict] = []
    n_contra = gold.count("contradiction")
    n_non = len(gold) - n_contra
    for th in thresholds:
        caught = sum(
            1 for g, c in zip(gold, contra_scores, strict=True)
            if g == "contradiction" and c >= th
        )
        false_veto = sum(
            1 for g, c in zip(gold, contra_scores, strict=True)
            if g != "contradiction" and c >= th
        )
        rows.append({
            "th": th,
            "contradiction_recall": round(caught / n_contra, 3) if n_contra else 0.0,
            "false_veto": false_veto,
            "false_veto_rate": round(false_veto / n_non, 3) if n_non else 0.0,
        })
    return rows


def load_gold(path: Path = GOLD_PATH) -> list[dict]:
    """JSONL gold-set yükle (boş satırlar atlanır)."""
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def run_nli(rows: list[dict]) -> tuple[list[str], list[float], list[float]]:
    """Her çift için NLI → (pred_labels, contradiction_scores, entailment_scores).

    verify_batch tek seferde (premise=evidence, hypothesis=claim sırası nli.py'de).
    Model main thread'de preload edilmiş olmalı (segfault guard).
    """
    from verifier.nli import get_verifier

    verifier = get_verifier()
    # NLIVerifier.verify_batch pairs = (claim=hypothesis, evidence=premise).
    pairs = [(r["hypothesis"], r["premise"]) for r in rows]
    results = verifier.verify_batch(pairs, batch_size=16)
    preds = [r.label for r in results]
    con = [r.contradiction_score for r in results]
    ent = [r.entailment_score for r in results]
    return preds, con, ent


def build_report(rows: list[dict]) -> dict:
    """Tam NLI-TR raporu — model yükler, ölçer (model GEREKİR)."""
    gold = [r["label"] for r in rows]
    preds, con, _ent = run_nli(rows)
    report = score_predictions(gold, preds)
    report["production_threshold"] = NLI_CONTRADICTION_THRESHOLD
    report["threshold_sweep"] = threshold_sweep(gold, con)
    # Production eşiğinde gerçek veto yanlış-pozitifi (argmax değil, eşik bazlı).
    n_non = report["n_non_contradiction"]
    prod_fv = sum(
        1 for g, c in zip(gold, con, strict=True)
        if g != "contradiction" and c >= NLI_CONTRADICTION_THRESHOLD
    )
    report["prod_false_veto"] = prod_fv
    report["prod_false_veto_rate"] = round(prod_fv / n_non, 3) if n_non else 0.0
    # Hata dökümü — yanlış sınıflanan çiftler (tanı için).
    report["misclassified"] = [
        {"id": r["id"], "gold": r["label"], "pred": p,
         "hypothesis": r["hypothesis"]}
        for r, p in zip(rows, preds, strict=True) if r["label"] != p
    ]
    return report


def print_scorecard(s: dict) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n  NLI-TR ÖLÇÜM (Faz-3) — {s['n']} Türkçe çift  "
          f"({s['n_non_contradiction']} non-contra / {s['n_contradiction']} contra)\n{bar}")
    print(f"  3-sınıf doğruluk = {s['accuracy']:.0%}")
    mark = "✅" if s["contra_false_positives"] == 0 else "⚠️"
    print(f"  {mark} argmax çelişki YANLIŞ-POZİTİF (iyi çifti çelişki sanma) = "
          f"{s['contra_false_positives']}/{s['n_non_contradiction']}  "
          f"({s['contra_false_positive_rate']:.0%})")
    print(f"  çelişki yakalama (recall) = {s['contradiction_recall']:.0%}  "
          f"({s['n_contradiction']} gerçek çelişki)")
    print(f"  {'-' * 68}")
    for lab, m in s["per_label"].items():
        print(f"  {lab:<16} P={m['precision']:<5} R={m['recall']:<5} F1={m['f1']:<5} "
              f"(tp={m['tp']} fp={m['fp']} fn={m['fn']})")
    if "threshold_sweep" in s:
        print(f"  {'-' * 68}")
        print(f"  Çelişki eşik taraması (production eşik={s['production_threshold']}):")
        for row in s["threshold_sweep"]:
            tag = "  <-- production" if abs(row["th"] - s["production_threshold"]) < 1e-9 else ""
            print(f"    th={row['th']:.2f}  yakalama={row['contradiction_recall']:.0%}  "
                  f"yanlış-veto={row['false_veto']}/{s['n_non_contradiction']} "
                  f"({row['false_veto_rate']:.0%}){tag}")
        print(f"  {'-' * 68}")
        pm = "✅" if s["prod_false_veto"] == 0 else "⚠️"
        print(f"  {pm} PRODUCTION eşiğinde ({s['production_threshold']}) veto yanlış-pozitif = "
              f"{s['prod_false_veto']}/{s['n_non_contradiction']} ({s['prod_false_veto_rate']:.0%})")
    if s.get("misclassified"):
        print(f"  {'-' * 68}\n  Yanlış sınıflananlar:")
        for m in s["misclassified"]:
            print(f"    [{m['id']}] gold={m['gold']:<14} pred={m['pred']:<14} "
                  f"« {m['hypothesis'][:48]} »")
    print(bar)


def preload_nli_sync() -> None:
    """NLI modelini main thread'de eager-load — Windows+torch segfault guard
    (verify_calibration.preload_nli_sync ile aynı desen)."""
    print("[*] NLI modeli yükleniyor (main thread, ~280MB)...", flush=True)
    from verifier.nli import get_verifier
    _ = get_verifier()._components  # cached_property tetikle
    print("[*] NLI hazır", flush=True)


if __name__ == "__main__":
    import argparse
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="NLI-TR yanlış-pozitif çelişki ölçümü")
    parser.add_argument("--gold", default=str(GOLD_PATH))
    parser.add_argument("--out", default=None, help="Scorecard JSON çıktısı")
    args = parser.parse_args()

    preload_nli_sync()
    rows = load_gold(Path(args.gold))
    scorecard = build_report(rows)
    print_scorecard(scorecard)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(scorecard, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Sonuç -> {out}")
