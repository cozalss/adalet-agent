"""Verify-layer kalibrasyon harness'i — eşikleri KÖRLEMESİNE değiştirme.

Sorun: `agents/config.py` içindeki verify eşikleri (FUZZY_SUPPORT_THRESHOLD,
LETTUCE_SUPPORT_THRESHOLD, NLI_*, MIN_VERIFIED_CLAIMS_RATIO) elle, ölçüm
yapılmadan ayarlandı — yorumlar bunu itiraf ediyor (`0.72→0.60→0.55`,
`0.50→0.30→0.20`). Bir eşiği kaydırmak verdict dağılımını (pass/retry/reject)
sessizce bozabilir. Bu harness, etiketli bir altın küme üzerinde verify
KARARINI ölçer → her eşik değişikliği artık ölçülen bir delta olur.

Veri: `data/eval_benchmark/verify_gold.jsonl` — (iddia, kanıt, should_support)
SENTETİK test fixture'ları. Madde numaraları fixture-içi tutarlı; bunlar
otoriter hukuki beyan DEĞİL, grounding kararını ölçmek için kurgulanmış
çiftlerdir (CLAUDE.md §1: kullanıcıya sunulan uydurma referans yok).

Ölçülen (DETERMİNİSTİK — model GEREKMEZ):
  - Layer 1 (rules): madde format sentaktik geçerlilik
  - Layer 2 (fuzzy): rapidfuzz snippet eşleşmesi
  - Layer 2.5 (lettuce FALLBACK): token-coverage (model yokken bu yol)
NLI (Layer 3) modeli gerektirir → opsiyonel (VERIFY_CAL_NLI=1), default kapalı
(Windows+torch segfault + 700MB indirme riskinden kaçınılır).

Önemli bulgu (production model-free yolu): `verify_node` lettuce support/veto
dallarını `not l25_fallback` ile kapılar; model yokken (fallback) yalnız
FUZZY + L1 karar verir. Harness bunu hem olduğu gibi ölçer hem de "lettuce
fallback skoru SİNYAL olsaydı" ayrımını raporlar.

Çalıştırma:
    uv run python -m eval.verify_calibration
    uv run python -m eval.verify_calibration --out eval/runs/verify_cal.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.config import (
    FUZZY_SUPPORT_THRESHOLD,
    LETTUCE_SUPPORT_THRESHOLD,
    MIN_VERIFIED_CLAIMS_RATIO,
    NLI_CONTRADICTION_THRESHOLD,
    NLI_ENTAILMENT_THRESHOLD,
)
from agents.nodes.verify import _verdict_from_ratio
from agents.state import Citation, Claim
from agents.verifier_layers import (
    layer1_rules,
    layer2_fuzzy,
    layer25_lettuce,
    pick_evidence,
)

GOLD_PATH = (
    Path(__file__).parent.parent / "data" / "eval_benchmark" / "verify_gold.jsonl"
)


@dataclass(frozen=True, slots=True)
class GoldCase:
    """Tek bir etiketli kalibrasyon vakası."""

    id: str
    category: str
    claim_text: str
    cite_ids: tuple[str, ...]
    evidence: tuple[dict[str, str], ...]
    should_support: bool


@dataclass(frozen=True, slots=True)
class CaseScore:
    """Bir vakanın deterministik katman skorları."""

    id: str
    category: str
    should_support: bool
    l1_ok: bool
    fuzzy: float
    lettuce: float


@dataclass(frozen=True, slots=True)
class Confusion:
    """İkili karar karışıklık matrisi (pozitif sınıf = supported)."""

    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def accuracy(self) -> float:
        total = self.tp + self.fp + self.tn + self.fn
        return (self.tp + self.tn) / total if total else 0.0


# --------------------------------------------------------------------------
#  Yükleme + dönüşüm
# --------------------------------------------------------------------------

def load_gold(path: Path = GOLD_PATH) -> list[GoldCase]:
    """JSONL altın kümeyi GoldCase listesine oku."""
    if not path.exists():
        raise FileNotFoundError(f"Verify altın küme bulunamadı: {path}")
    cases: list[GoldCase] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            cases.append(
                GoldCase(
                    id=raw["id"],
                    category=raw["category"],
                    claim_text=raw["claim"],
                    cite_ids=tuple(raw.get("cite_ids", [])),
                    evidence=tuple(raw.get("evidence", [])),
                    should_support=bool(raw["should_support"]),
                ),
            )
    return cases


def _to_claim(gc: GoldCase) -> Claim:
    return Claim(
        text=gc.claim_text,
        cite_ids=list(gc.cite_ids),
        verified=False,
        verify_score=0.0,
        verify_reason="",
    )


def _to_refs(gc: GoldCase) -> list[Citation]:
    refs: list[Citation] = []
    for ev in gc.evidence:
        refs.append(
            Citation(
                source_id=ev.get("source_id", ""),
                doc_type="law",
                title=ev.get("title", ""),
                snippet=ev.get("snippet", ""),
                url="",
                score=1.0,
            ),
        )
    return refs


# --------------------------------------------------------------------------
#  Skorlama (deterministik katmanlar)
# --------------------------------------------------------------------------

async def score_case(gc: GoldCase) -> CaseScore:
    """L1/L2/L2.5 deterministik skorlarını üret (NLI yok)."""
    claim = _to_claim(gc)
    refs = _to_refs(gc)
    l1_ok, _ = layer1_rules(claim)
    fuzzy, _, _ = layer2_fuzzy(claim, refs)
    lettuce_results = await layer25_lettuce([claim], refs)
    lettuce_score = lettuce_results[0][0] if lettuce_results else 0.0
    return CaseScore(
        id=gc.id,
        category=gc.category,
        should_support=gc.should_support,
        l1_ok=l1_ok,
        fuzzy=fuzzy,
        lettuce=lettuce_score,
    )


async def score_all(cases: list[GoldCase]) -> list[CaseScore]:
    return [await score_case(gc) for gc in cases]


# --------------------------------------------------------------------------
#  Karar fonksiyonları (production verify_node ile aynı mantık)
# --------------------------------------------------------------------------

def support_modelfree(cs: CaseScore, fuzzy_th: float) -> bool:
    """Production model-free yolu: format geçerli VE fuzzy >= eşik.

    `verify_node` lettuce dallarını `not l25_fallback` ile kapılar; model
    yokken yalnız L1 + fuzzy karar verir. Bu fonksiyon o yolu birebir yansıtır.
    """
    return cs.l1_ok and cs.fuzzy >= fuzzy_th


def support_with_lettuce(cs: CaseScore, fuzzy_th: float, lettuce_th: float) -> bool:
    """Hipotetik: lettuce fallback skoru da pozitif sinyal sayılsaydı.

    L1 geçerli VE (fuzzy >= fuzzy_th VEYA lettuce >= lettuce_th). Bu production
    DEĞİL — fallback token-coverage'in sinyal değeri olup olmadığını ölçmek için.
    """
    if not cs.l1_ok:
        return False
    return cs.fuzzy >= fuzzy_th or cs.lettuce >= lettuce_th


def contradiction_detected(con: float, threshold: float) -> bool:
    """NLI çelişki vetosu — production `layer3_nli_batch` ile aynı eşik mantığı."""
    return con >= threshold


def support_full(
    cs: CaseScore,
    ent: float,
    con: float,
    fuzzy_th: float,
    nli_ent_th: float,
    contra_th: float,
) -> bool:
    """TAM production kararı (NLI + fuzzy + lettuce-fallback).

    `verify_node` sırası: çelişki vetosu → format → fuzzy → (lettuce: fallback'te
    atlanır) → NLI entailment fallback. Lettuce fallback modunda support/veto
    dalları kapalı olduğundan karar = çelişki yok VE L1 VE (fuzzy|NLI-entail).
    """
    if contradiction_detected(con, contra_th):
        return False
    if not cs.l1_ok:
        return False
    return cs.fuzzy >= fuzzy_th or ent >= nli_ent_th


def confusion(decisions: list[bool], golds: list[bool]) -> Confusion:
    """Karar listesi vs altın etiket → karışıklık matrisi."""
    tp = fp = tn = fn = 0
    for dec, gold in zip(decisions, golds, strict=True):
        if dec and gold:
            tp += 1
        elif dec and not gold:
            fp += 1
        elif not dec and not gold:
            tn += 1
        else:
            fn += 1
    return Confusion(tp=tp, fp=fp, tn=tn, fn=fn)


def sweep(
    scores: list[CaseScore],
    thresholds: list[float],
    decide: Any,
) -> list[tuple[float, Confusion]]:
    """Her eşik için karar + karışıklık matrisi (decide: (cs, th) -> bool)."""
    golds = [cs.should_support for cs in scores]
    out: list[tuple[float, Confusion]] = []
    for th in thresholds:
        decisions = [decide(cs, th) for cs in scores]
        out.append((th, confusion(decisions, golds)))
    return out


def separation(scores: list[CaseScore], value: Any) -> tuple[float, float, float]:
    """should_support True/False gruplarının ortalama skor + ayrım payı."""
    pos = [value(cs) for cs in scores if cs.should_support]
    neg = [value(cs) for cs in scores if not cs.should_support]
    mean_pos = sum(pos) / len(pos) if pos else 0.0
    mean_neg = sum(neg) / len(neg) if neg else 0.0
    return mean_pos, mean_neg, mean_pos - mean_neg


def verdict_table(
    min_ratios: list[float],
    supported_ratios: list[float],
) -> list[tuple[float, list[tuple[float, str]]]]:
    """`_verdict_from_ratio`'ı karakterize et (saf fonksiyon, model yok).

    Her MIN_VERIFIED_CLAIMS_RATIO adayı için, çeşitli supported-oranlarında
    hangi verdict üretildiğini gösterir (contradiction=0, retry_count=0).
    """
    state: dict[str, Any] = {"retry_count": 0}
    table: list[tuple[float, list[tuple[float, str]]]] = []
    for min_ratio in min_ratios:
        import agents.nodes.verify as _v

        original = _v.MIN_VERIFIED_CLAIMS_RATIO
        _v.MIN_VERIFIED_CLAIMS_RATIO = min_ratio
        try:
            row: list[tuple[float, str]] = []
            for sr in supported_ratios:
                n_total = 10
                n_supported = round(sr * n_total)
                verdict = _verdict_from_ratio(n_supported, n_total, state, 0)
                row.append((sr, verdict))
            table.append((min_ratio, row))
        finally:
            _v.MIN_VERIFIED_CLAIMS_RATIO = original
    return table


# --------------------------------------------------------------------------
#  Raporlama
# --------------------------------------------------------------------------

def _fmt_row(th: float, cm: Confusion) -> str:
    return (
        f"  th={th:.2f}  P={cm.precision:.2f} R={cm.recall:.2f} "
        f"F1={cm.f1:.2f} Acc={cm.accuracy:.2f}  "
        f"(TP={cm.tp} FP={cm.fp} TN={cm.tn} FN={cm.fn})"
    )


def build_report(scores: list[CaseScore]) -> dict[str, Any]:
    """Tam kalibrasyon raporunu dict olarak üret (JSON'a yazılabilir)."""
    fuzzy_ths = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    lettuce_ths = [0.30, 0.40, 0.45, 0.50, 0.60]

    fuzzy_sweep = sweep(scores, fuzzy_ths, support_modelfree)
    current = confusion(
        [support_modelfree(cs, FUZZY_SUPPORT_THRESHOLD) for cs in scores],
        [cs.should_support for cs in scores],
    )
    fuzzy_sep = separation(scores, lambda cs: cs.fuzzy)
    lettuce_sep = separation(scores, lambda cs: cs.lettuce)
    lettuce_sweep = sweep(
        scores, lettuce_ths,
        lambda cs, th: support_with_lettuce(cs, FUZZY_SUPPORT_THRESHOLD, th),
    )
    return {
        "n_cases": len(scores),
        "n_should_support": sum(cs.should_support for cs in scores),
        "current_thresholds": {
            "FUZZY_SUPPORT_THRESHOLD": FUZZY_SUPPORT_THRESHOLD,
            "LETTUCE_SUPPORT_THRESHOLD": LETTUCE_SUPPORT_THRESHOLD,
            "MIN_VERIFIED_CLAIMS_RATIO": MIN_VERIFIED_CLAIMS_RATIO,
        },
        "current_modelfree": {
            "precision": round(current.precision, 4),
            "recall": round(current.recall, 4),
            "f1": round(current.f1, 4),
            "accuracy": round(current.accuracy, 4),
            "tp": current.tp, "fp": current.fp,
            "tn": current.tn, "fn": current.fn,
        },
        "fuzzy_sweep": [
            {"th": th, "precision": round(cm.precision, 4),
             "recall": round(cm.recall, 4), "f1": round(cm.f1, 4),
             "accuracy": round(cm.accuracy, 4)}
            for th, cm in fuzzy_sweep
        ],
        "fuzzy_separation": {
            "mean_supported": round(fuzzy_sep[0], 4),
            "mean_unsupported": round(fuzzy_sep[1], 4),
            "gap": round(fuzzy_sep[2], 4),
        },
        "lettuce_separation": {
            "mean_supported": round(lettuce_sep[0], 4),
            "mean_unsupported": round(lettuce_sep[1], 4),
            "gap": round(lettuce_sep[2], 4),
        },
        "lettuce_sweep_asif": [
            {"th": th, "precision": round(cm.precision, 4),
             "recall": round(cm.recall, 4), "f1": round(cm.f1, 4)}
            for th, cm in lettuce_sweep
        ],
        "per_category": _category_breakdown(scores),
    }


# --------------------------------------------------------------------------
#  NLI yolu (opsiyonel — model gerektirir, --nli ile etkin)
# --------------------------------------------------------------------------

def preload_nli_sync() -> None:
    """NLI modelini main thread'de eager-load — Windows+asyncio+torch segfault'u
    önler (freeze_baseline._preload_models_sync ile aynı desen)."""
    print("[*] NLI modeli yükleniyor (main thread, ~280MB)...", flush=True)
    from verifier.nli import get_verifier
    _ = get_verifier()._components  # cached_property tetikle
    print("[*] NLI hazır", flush=True)


def nli_scores(cases: list[GoldCase]) -> dict[str, tuple[float, float, str]]:
    """Her vaka için en alakalı kanıtla NLI → {id: (ent, con, label)}.

    Tek batch (verify_batch) — production `layer3_nli_batch` ile aynı pair seçimi
    (pick_evidence). Model main thread'de preload edilmiş olmalı.
    """
    from verifier.nli import get_verifier

    verifier = get_verifier()
    pairs: list[tuple[str, str]] = []
    for gc in cases:
        claim = _to_claim(gc)
        pairs.append((claim["text"], pick_evidence(claim, _to_refs(gc))))
    results = verifier.verify_batch(pairs, batch_size=16)
    return {
        gc.id: (r.entailment_score, r.contradiction_score, r.label)
        for gc, r in zip(cases, results, strict=True)
    }


def build_nli_section(
    scores: list[CaseScore],
    nli: dict[str, tuple[float, float, str]],
) -> dict[str, Any]:
    """NLI dahil tam-pipeline kararı + çelişki yakalama metrikleri."""
    golds = [cs.should_support for cs in scores]
    decisions = [
        support_full(
            cs, nli[cs.id][0], nli[cs.id][1],
            FUZZY_SUPPORT_THRESHOLD, NLI_ENTAILMENT_THRESHOLD,
            NLI_CONTRADICTION_THRESHOLD,
        )
        for cs in scores
    ]
    full_cm = confusion(decisions, golds)

    contra_cases = [cs for cs in scores if cs.category == "contradiction"]
    contra_sweep = []
    for th in [0.50, 0.60, 0.70, 0.80, 0.90]:
        detected = sum(
            1 for cs in contra_cases
            if contradiction_detected(nli[cs.id][1], th)
        )
        # yanlış-veto: should_support=True iken çelişki sanılan
        false_veto = sum(
            1 for cs in scores
            if cs.should_support and contradiction_detected(nli[cs.id][1], th)
        )
        contra_sweep.append({
            "th": th,
            "contradiction_recall": round(detected / len(contra_cases), 4)
            if contra_cases else 0.0,
            "false_veto_on_supported": false_veto,
        })

    ent_sep = separation(scores, lambda cs: nli[cs.id][0])
    return {
        "full_pipeline": {
            "precision": round(full_cm.precision, 4),
            "recall": round(full_cm.recall, 4),
            "f1": round(full_cm.f1, 4),
            "accuracy": round(full_cm.accuracy, 4),
            "tp": full_cm.tp, "fp": full_cm.fp,
            "tn": full_cm.tn, "fn": full_cm.fn,
        },
        "contradiction_threshold_sweep": contra_sweep,
        "entailment_separation": {
            "mean_supported": round(ent_sep[0], 4),
            "mean_unsupported": round(ent_sep[1], 4),
            "gap": round(ent_sep[2], 4),
        },
    }


def print_nli_section(section: dict[str, Any]) -> None:
    fp = section["full_pipeline"]
    print("\n  TAM PIPELINE (NLI + fuzzy + L1) mevcut eşiklerde:")
    print(f"    P={fp['precision']:.2f} R={fp['recall']:.2f} "
          f"F1={fp['f1']:.2f} Acc={fp['accuracy']:.2f}  "
          f"(TP={fp['tp']} FP={fp['fp']} TN={fp['tn']} FN={fp['fn']})")
    print("\n  NLI çelişki eşiği taraması "
          "(contradiction kategorisi yakalama / supported'a yanlış-veto):")
    for row in section["contradiction_threshold_sweep"]:
        print(f"    th={row['th']:.2f}  recall={row['contradiction_recall']:.2f}  "
              f"yanlış-veto={row['false_veto_on_supported']}")
    es = section["entailment_separation"]
    print(f"\n  NLI entailment ayrım: supported={es['mean_supported']:.2f}  "
          f"unsupported={es['mean_unsupported']:.2f}  gap={es['gap']:+.2f}")


def _category_breakdown(scores: list[CaseScore]) -> dict[str, dict[str, float]]:
    """Kategori başına ortalama fuzzy/lettuce + mevcut karar doğruluğu."""
    cats: dict[str, list[CaseScore]] = {}
    for cs in scores:
        cats.setdefault(cs.category, []).append(cs)
    out: dict[str, dict[str, float]] = {}
    for cat, items in sorted(cats.items()):
        decisions = [support_modelfree(cs, FUZZY_SUPPORT_THRESHOLD) for cs in items]
        correct = sum(
            1 for cs, dec in zip(items, decisions, strict=True)
            if dec == cs.should_support
        )
        out[cat] = {
            "n": len(items),
            "mean_fuzzy": round(sum(cs.fuzzy for cs in items) / len(items), 4),
            "mean_lettuce": round(sum(cs.lettuce for cs in items) / len(items), 4),
            "decision_accuracy": round(correct / len(items), 4),
        }
    return out


def print_report(report: dict[str, Any], scores: list[CaseScore]) -> None:
    print("\n" + "=" * 64)
    print("  VERIFY KALİBRASYON RAPORU (deterministik: L1 + fuzzy + lettuce)")
    print("=" * 64)
    print(f"  Vaka: {report['n_cases']}  |  should_support: "
          f"{report['n_should_support']}")
    cur = report["current_modelfree"]
    print(f"\n  MEVCUT eşik (FUZZY={FUZZY_SUPPORT_THRESHOLD}) model-free karar:")
    print(f"    P={cur['precision']:.2f} R={cur['recall']:.2f} "
          f"F1={cur['f1']:.2f} Acc={cur['accuracy']:.2f}  "
          f"(TP={cur['tp']} FP={cur['fp']} TN={cur['tn']} FN={cur['fn']})")

    print("\n  FUZZY eşik taraması (karar = L1 ve fuzzy>=th):")
    fuzzy_ths = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    for th, cm in sweep(scores, fuzzy_ths, support_modelfree):
        print(_fmt_row(th, cm))

    fs = report["fuzzy_separation"]
    ls = report["lettuce_separation"]
    print(f"\n  Fuzzy ayrım:   supported={fs['mean_supported']:.2f}  "
          f"unsupported={fs['mean_unsupported']:.2f}  gap={fs['gap']:+.2f}")
    print(f"  Lettuce ayrım: supported={ls['mean_supported']:.2f}  "
          f"unsupported={ls['mean_unsupported']:.2f}  gap={ls['gap']:+.2f}")

    print("\n  Kategori kırılımı (mevcut eşikte karar doğruluğu):")
    for cat, m in report["per_category"].items():
        print(f"    {cat:14s} n={int(m['n']):2d}  fuzzy={m['mean_fuzzy']:.2f}  "
              f"lettuce={m['mean_lettuce']:.2f}  acc={m['decision_accuracy']:.2f}")

    print("\n  MIN_VERIFIED_CLAIMS_RATIO karakterizasyonu "
          "(supported-oranı → verdict):")
    ratios = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
    for min_ratio, row in verdict_table([0.20, 0.30, 0.50], ratios):
        cells = "  ".join(f"{sr:.1f}:{v[:4]}" for sr, v in row)
        print(f"    MIN_RATIO={min_ratio:.2f}  {cells}")
    print()


async def main() -> int:
    # Windows konsolu cp1254 → Türkçe + '->' gibi karakterlerde UnicodeEncodeError.
    # stdout'u UTF-8'e çevir (mümkünse); raporun düzgün basılmasını garanti et.
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None, help="Raporu JSON'a yaz")
    parser.add_argument(
        "--nli", action="store_true",
        help="NLI modelini de çalıştır (model preload __main__'de yapılmalı)",
    )
    args = parser.parse_args()

    cases = load_gold()
    scores = await score_all(cases)
    report = build_report(scores)
    print_report(report, scores)

    if args.nli:
        nli = await asyncio.to_thread(nli_scores, cases)
        nli_section = build_nli_section(scores, nli)
        report["nli"] = nli_section
        print_nli_section(nli_section)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(f"  Rapor yazıldı: {args.out}")
    return 0


if __name__ == "__main__":
    # NLI model'i asyncio.run ÖNCESİ main thread'de yükle (segfault guard).
    if "--nli" in sys.argv:
        preload_nli_sync()
    sys.exit(asyncio.run(main()))
