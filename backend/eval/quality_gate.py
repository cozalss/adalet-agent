"""Prompt kalite kapısı — prompt değişikliğini ÖLÇÜLÜ kabul/ret eder.

"Prompt'u uzat" demeden önce kapı koy (kullanıcı direktifi). Bu modül bir baseline
ve bir candidate (yeni prompt) scorecard'ını karşılaştırır ve şu kriterlere göre
PASS/FAIL verir:

  1. length_in_target_rate ARTMALI (asıl hedef: 160-220 kelimeye yaklaş)
  2. has_short_answer_rate korunmalı (format işareti düşmesin)
  3. truncation_rate ARTMAMALI (cevap kesilmesi yok)
  4. src_coverage (kaynak-bağı) DÜŞMEMELİ (epsilon toleransı)
  5. unsupported_claim_rate ARTMAMALI (kaynaksız iddia çoğalmasın)
  6. p95_ms aşırı BOZULMAMALI (uzunluk artışı latansı patlatmasın)

Saf gate mantığı (gate_verdict) LLM'siz test edilebilir; harness (run_scorecard)
graph'ı koşturur. Kullanım:

    # baseline (mevcut prompt)
    LLM_MODE=llamacpp_server uv run python -m eval.quality_gate --run --out eval/runs/gate_base.json
    # candidate (yeni prompt) — prompt değişikliğinden sonra
    LLM_MODE=llamacpp_server uv run python -m eval.quality_gate --run --out eval/runs/gate_cand.json
    # kapı kararı
    uv run python -m eval.quality_gate --gate eval/runs/gate_base.json eval/runs/gate_cand.json
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass

# Tolerans/eşik sabitleri — kalite gerilemesine izin verilen küçük pay.
_SRC_DROP_TOLERANCE = 0.03       # kaynak-bağı bu kadar düşebilir (gürültü payı)
_UNSUPPORTED_TOLERANCE = 0.02    # kaynaksız iddia oranı bu kadar artabilir
_P95_DEGRADE_FACTOR = 1.20       # P95 en fazla %20 bozulabilir
_SHORT_ANSWER_DROP_TOLERANCE = 0.05  # format işareti bu kadar düşebilir


@dataclass(frozen=True)
class Scorecard:
    """Bir prompt sürümünün N vaka üzerindeki kalite özeti."""

    n: int
    length_in_target_rate: float
    has_short_answer_rate: float
    truncation_rate: float
    avg_src_coverage: float
    unsupported_claim_rate: float   # kaynaksız iddia içeren cevap oranı
    avg_word_count: float
    p95_ms: float

    def to_dict(self) -> dict:
        return asdict(self)


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return round(s[max(0, math.ceil(len(s) * p) - 1)], 1)


def score_answers(rows: list[dict]) -> Scorecard:
    """Ölçüm satırlarından (measure + measure_risk + elapsed_ms) scorecard üret.

    Her row: {length_in_target, has_short_answer, is_truncated, src_coverage,
              word_count, unsupported_claims, elapsed_ms} (kısa-devre hariç).
    """
    ok = [r for r in rows if r.get("elapsed_ms", 0) > 1000]  # gerçek hukuki cevaplar
    n = len(ok) or 1
    return Scorecard(
        n=len(ok),
        length_in_target_rate=round(sum(r["length_in_target"] for r in ok) / n, 4),
        has_short_answer_rate=round(sum(r["has_short_answer"] for r in ok) / n, 4),
        truncation_rate=round(sum(r["is_truncated"] for r in ok) / n, 4),
        avg_src_coverage=round(sum(r["src_coverage"] for r in ok) / n, 4),
        unsupported_claim_rate=round(
            sum(1 for r in ok if r.get("unsupported_claims", 0) > 0) / n, 4),
        avg_word_count=round(sum(r["word_count"] for r in ok) / n, 1),
        p95_ms=_pct([r["elapsed_ms"] for r in ok], 0.95),
    )


@dataclass(frozen=True)
class Criterion:
    name: str
    passed: bool
    baseline: float
    candidate: float
    detail: str


def gate_verdict(baseline: Scorecard, candidate: Scorecard) -> dict:
    """Baseline vs candidate → kapı kararı (PASS/FAIL + kriter dökümü).

    Saf fonksiyon — LLM'siz test edilebilir.
    """
    crit: list[Criterion] = []

    # 1. Hedef-uzunluk ARTMALI (asıl amaç)
    crit.append(Criterion(
        "length_in_target ↑", candidate.length_in_target_rate >= baseline.length_in_target_rate,
        baseline.length_in_target_rate, candidate.length_in_target_rate,
        "hedef 160-220 kelime oranı düşmemeli (artması beklenir)"))

    # 2. has_short_answer korunmalı (format)
    crit.append(Criterion(
        "has_short_answer korunur",
        candidate.has_short_answer_rate >= baseline.has_short_answer_rate - _SHORT_ANSWER_DROP_TOLERANCE,
        baseline.has_short_answer_rate, candidate.has_short_answer_rate,
        f"format işareti en fazla {_SHORT_ANSWER_DROP_TOLERANCE} düşebilir"))

    # 3. truncation ARTMAMALI
    crit.append(Criterion(
        "truncation ↛", candidate.truncation_rate <= baseline.truncation_rate,
        baseline.truncation_rate, candidate.truncation_rate,
        "cevap kesilme oranı artmamalı"))

    # 4. src_coverage DÜŞMEMELİ
    crit.append(Criterion(
        "src_coverage korunur",
        candidate.avg_src_coverage >= baseline.avg_src_coverage - _SRC_DROP_TOLERANCE,
        baseline.avg_src_coverage, candidate.avg_src_coverage,
        f"kaynak-bağı en fazla {_SRC_DROP_TOLERANCE} düşebilir"))

    # 5. unsupported_claim ARTMAMALI
    crit.append(Criterion(
        "unsupported ↛",
        candidate.unsupported_claim_rate <= baseline.unsupported_claim_rate + _UNSUPPORTED_TOLERANCE,
        baseline.unsupported_claim_rate, candidate.unsupported_claim_rate,
        f"kaynaksız iddia oranı en fazla {_UNSUPPORTED_TOLERANCE} artabilir"))

    # 6. P95 aşırı BOZULMAMALI
    p95_ceiling = baseline.p95_ms * _P95_DEGRADE_FACTOR
    crit.append(Criterion(
        "p95 korunur", candidate.p95_ms <= p95_ceiling,
        baseline.p95_ms, candidate.p95_ms,
        f"P95 en fazla %{int((_P95_DEGRADE_FACTOR - 1) * 100)} bozulabilir (tavan {p95_ceiling:.0f}ms)"))

    passed = all(c.passed for c in crit)
    return {
        "passed": passed,
        "criteria": [asdict(c) for c in crit],
        "baseline": baseline.to_dict(),
        "candidate": candidate.to_dict(),
    }


def print_gate(verdict: dict) -> None:
    print(f"\n{'=' * 70}")
    print(f"  PROMPT KALİTE KAPISI — {'✅ GEÇTİ' if verdict['passed'] else '❌ KALDI'}")
    print(f"{'=' * 70}")
    for c in verdict["criteria"]:
        mark = "✅" if c["passed"] else "❌"
        print(f"  {mark} {c['name']:<26} base={c['baseline']:<8} cand={c['candidate']:<8}")
        if not c["passed"]:
            print(f"      → {c['detail']}")
    print(f"{'=' * 70}")


# --------------------------------------------------------------------------- #
# Harness — graph koşturma (LLM gerekir)
# --------------------------------------------------------------------------- #

async def run_scorecard(version: str, n: int) -> tuple[Scorecard, list[dict]]:
    import asyncio
    import time

    from agents.graph import build_graph
    from agents.state import AgentState
    from eval.answer_risk import measure_risk
    from eval.draft_quality import measure, strip_boilerplate_block
    from scripts.eval_run import _load_benchmark

    cases = _load_benchmark(version)[:n]
    graph = build_graph()
    # 2 ısınma — ilk LLM çağrısı soğuk-start (model paging) P95'i şişirir.
    # İki ısınma ile ölçüm penceresi tamamen ısınmış olur; A/B adil kalır.
    for _w in ("ısınma bir", "ısınma iki"):
        await graph.ainvoke(AgentState(question=_w))

    rows = []
    for i, case in enumerate(cases, 1):
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                graph.ainvoke(AgentState(question=case["soru"])), timeout=90)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            resp = result.get("response", "") or ""
            m = measure(resp)
            risk = measure_risk(strip_boilerplate_block(resp))
            rows.append({**m, "unsupported_claims": risk["unsourced_claims"],
                         "elapsed_ms": elapsed_ms})
            print(f"  [{i:>2}/{len(cases)}] {elapsed_ms:>7.0f}ms  {m['word_count']}w", flush=True)
        except asyncio.TimeoutError:
            rows.append({"length_in_target": False, "has_short_answer": False,
                         "is_truncated": False, "src_coverage": 0, "word_count": 0,
                         "unsupported_claims": 0, "elapsed_ms": 90000})
    return score_answers(rows), rows


if __name__ == "__main__":
    import argparse
    import asyncio
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Prompt kalite kapısı")
    parser.add_argument("--run", action="store_true", help="Scorecard üret (graph koşar)")
    parser.add_argument("--version", default="v1", choices=["v1", "v2"])
    parser.add_argument("--n", type=int, default=15)
    parser.add_argument("--out", default=None)
    parser.add_argument("--gate", nargs=2, metavar=("BASELINE", "CANDIDATE"),
                        help="İki scorecard JSON → kapı kararı")
    args = parser.parse_args()

    if args.gate:
        base = Scorecard(**json.loads(Path(args.gate[0]).read_text(encoding="utf-8"))["scorecard"])
        cand = Scorecard(**json.loads(Path(args.gate[1]).read_text(encoding="utf-8"))["scorecard"])
        v = gate_verdict(base, cand)
        print_gate(v)
        sys.exit(0 if v["passed"] else 1)

    if args.run:
        from core import native_preload  # noqa: F401
        sc, rows = asyncio.run(run_scorecard(args.version, args.n))
        print(f"\n  Scorecard: hedef-uzunluk={sc.length_in_target_rate:.0%} "
              f"kısa-cvp={sc.has_short_answer_rate:.0%} kesilme={sc.truncation_rate:.0%} "
              f"src={sc.avg_src_coverage:.0%} kelime={sc.avg_word_count} P95={sc.p95_ms:.0f}ms")
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"scorecard": sc.to_dict(), "rows": rows},
                                      indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  Sonuc -> {out}")
