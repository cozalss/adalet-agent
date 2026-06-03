"""Yarışma karnesi — tüm DETERMİNİSTİK (LLM'siz) kalkan-metriklerini tek jüri-hazır
artefakta toplar.

ADALET'in başlık iddiası "SIFIR HALÜSİNASYON + valid cevabı bozmama"dır. Bu iddianın
kanıtı dağınık harness'lardaydı (hallucination_eval, eligibility_eval). Bu modül onları
TEK komutta koşturur, PASS/FAIL verir ve `docs/benchmark/scorecard.md` jüri raporunu üretir.

Saf/anında: LLM, GPU, ağ GEREKMEZ → CI'da her commit'te koşabilir (regresyon kapısı).
Gerçek-LLM gerektiren ölçümler (RAG faithfulness, full-pipeline kalite) AYRI koşar
(quality_gate.py, ragas_full.py) — bilerek bu karnenin dışında (karne deterministik kalsın).

Çalıştır:
    cd backend && uv run python -m eval.scorecard            # konsol + docs/benchmark/scorecard.md
    uv run python -m eval.scorecard --check                  # yalnız PASS/FAIL (CI exit-code)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_BENCH = _BACKEND / "data" / "eval_benchmark"
_DOC_OUT = _BACKEND.parent / "docs" / "benchmark" / "scorecard.md"

# Karneye yansıyan veri setleri (kapsam/breadth kanıtı — saf satır sayımı).
_COVERAGE_SETS = (
    ("hallucination_gold.jsonl", "Halüsinasyon adversarial gold"),
    ("eligibility_adversarial.jsonl", "Süre-uygunluk FABRİKE-eşik gold"),
    ("verify_gold.jsonl", "Doğrulama (verify) gold"),
    ("nli_tr_gold.jsonl", "Türkçe NLI gold"),
    ("benchmark_v2.jsonl", "Ana benchmark (v2)"),
    ("out_of_scope_cases.jsonl", "Kapsam-dışı (ceza/aile) vakaları"),
    ("prompt_injection_cases.jsonl", "Prompt-injection vakaları"),
)


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_BACKEND), capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _count_jsonl(name: str) -> int:
    p = _BENCH / name
    if not p.exists():
        return 0
    return sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())


def _dataset_coverage() -> list[dict]:
    return [{"set": name, "label": label, "n": _count_jsonl(name)}
            for name, label in _COVERAGE_SETS]


def build_scorecard() -> dict:
    """Tüm deterministik kalkan-metriklerini koş → tek karne sözlüğü (saf, LLM'siz)."""
    from eval.eligibility_eval import evaluate as elig_evaluate
    from eval.eligibility_eval import load_gold as load_elig
    from eval.hallucination_eval import load_gold as load_hallu
    from eval.hallucination_eval import score_gold
    from eval.stats import wilson_interval

    hallu = score_gold(load_hallu(str(_BENCH / "hallucination_gold.jsonl")))
    elig = elig_evaluate(load_elig())

    def _ci(k: int, n: int) -> list[float]:
        lo, hi = wilson_interval(k, n)
        return [round(lo, 3), round(hi, 3)]

    # Kalkan PASS koşulu (kırmızı çizgi): hiç yanlış-veto YOK + tam yakalama +
    # FABRİKE-eşik precision tam (valid cevabı asla bozma garantisi).
    shield_pass = (
        hallu["veto_false_positives"] == 0
        and hallu["hallucination_recall"] == 1.0
        and hallu["micro_precision"] == 1.0
        and elig["precision"] == 1.0
    )

    return {
        "git_sha": _git_sha(),
        "shield_pass": shield_pass,
        "hallucination_shield": {
            "n": hallu["n"],
            "n_clean": hallu["n_clean"],
            "n_risky": hallu["n_bad"],
            "micro_precision": hallu["micro_precision"],
            "micro_recall": hallu["micro_recall"],
            "hallucination_recall": hallu["hallucination_recall"],
            # %95 Wilson CI (küçük-N dürüstlüğü): recall=caught/n_risky.
            "hallucination_recall_ci95": _ci(hallu["caught"], hallu["n_bad"]),
            "false_veto_count": hallu["veto_false_positives"],
            "false_veto_rate": hallu["veto_fp_rate"],
            # Yanlış-veto oranının %95 ÜST-sınırı (0/32 → 'üst-sınırla X'in altında').
            "false_veto_rate_upper95": round(
                wilson_interval(hallu["veto_false_positives"], hallu["n_clean"])[1], 3),
            "per_type": {t: {"precision": m["precision"], "recall": m["recall"], "f1": m["f1"]}
                        for t, m in hallu["per_type"].items()},
        },
        "fabricated_threshold": {
            "n": elig["n"],
            "precision": elig["precision"],
            "recall": elig["recall"],
            "f1": elig["f1"],
            "accuracy": elig["accuracy"],
            "precision_ci95": _ci(elig["tp"], elig["tp"] + elig["fp"]),
            "recall_ci95": _ci(elig["tp"], elig["tp"] + elig["fn"]),
        },
        "dataset_coverage": _dataset_coverage(),
    }


def render_markdown(sc: dict) -> str:
    """Karne sözlüğü → jüri-hazır Markdown (deterministik; sadece git SHA, zaman damgası yok)."""
    hs = sc["hallucination_shield"]
    ft = sc["fabricated_threshold"]
    verdict = "✅ GEÇTİ" if sc["shield_pass"] else "❌ KALDI"
    lines: list[str] = [
        "# ADALET — Sıfır-Halüsinasyon Kalkanı Karnesi",
        "",
        "> Deterministik (LLM'siz) ölçüm · `uv run python -m eval.scorecard` ile üretilir "
        "(üreten commit SHA'sı konsol çıktısında + `eval/runs/scorecard.json`'da).",
        "",
        f"**Genel durum: {verdict}** — temiz cevap asla reddedilmez (yanlış-veto=0) ve "
        "her riskli cevap yakalanır.",
        "",
        "## 1. Halüsinasyon kalkanı (içerik-risk detektörleri)",
        "",
        f"- Vaka: **{hs['n']}** ({hs['n_clean']} temiz / {hs['n_risky']} riskli, adversarial)",
        f"- Mikro precision: **{hs['micro_precision']}** · mikro recall: **{hs['micro_recall']}**",
        f"- Halüsinasyon yakalama (recall): **{hs['hallucination_recall']:.0%}** "
        f"(%95 Wilson CI [{hs['hallucination_recall_ci95'][0]:.3f}, "
        f"{hs['hallucination_recall_ci95'][1]:.3f}])",
        f"- **Yanlış-veto (iyi cevabı reddetme): {hs['false_veto_count']}/{hs['n_clean']} "
        f"({hs['false_veto_rate']:.0%})** ← kritik garanti "
        f"(oran %95 üst-sınır ≤ {hs['false_veto_rate_upper95']:.1%})",
        "",
        "| Detektör türü | Precision | Recall | F1 |",
        "|---|---|---|---|",
    ]
    type_tr = {
        "fabricated_law": "Uydurma kanun adı",
        "negative_eligibility": "Süre/eşik hak-reddi",
        "fabricated_citation": "İmkânsız mahkeme dairesi",
        "implausible_article": "İmkânsız madde no",
        "unsourced_claim": "Kaynaksız iddia",
    }
    for t, m in hs["per_type"].items():
        lines.append(f"| {type_tr.get(t, t)} | {m['precision']} | {m['recall']} | {m['f1']} |")
    lines += [
        "",
        "## 2. Süre-uygunluk FABRİKE-eşik ayrımı (kaynak-temelli, deterministik)",
        "",
        "Tehlikeli yanlış-çıkarımın (\"5 yıldan az tazminat verilmez\" = uydurma eşik) "
        "DOĞRU bilgilendirmeden (\"1 yılın altında kıdem doğmaz\" = kaynakta var) ayrımı.",
        "",
        f"- Vaka: **{ft['n']}** adversarial · precision: **{ft['precision']}** "
        f"(%95 CI [{ft['precision_ci95'][0]:.3f}, {ft['precision_ci95'][1]:.3f}]) · "
        f"recall: **{ft['recall']}** (%95 CI [{ft['recall_ci95'][0]:.3f}, "
        f"{ft['recall_ci95'][1]:.3f}]) · F1: **{ft['f1']}** · doğruluk: **{ft['accuracy']}**",
        "",
        "> Küçük-N notu: nokta-tahminleri (P=1.0) yanıltabilir; Wilson %95 güven aralıkları "
        "örneklem belirsizliğini dürüstçe gösterir. Setler büyüdükçe aralıklar daralır.",
        "",
        "## 3. Veri seti kapsamı (test tabanı breadth)",
        "",
        "| Set | Açıklama | Vaka |",
        "|---|---|---|",
    ]
    for c in sc["dataset_coverage"]:
        lines.append(f"| `{c['set']}` | {c['label']} | {c['n']} |")
    lines += [
        "",
        "---",
        "",
        "> Bu karne YALNIZ deterministik (kural/regex/eşik-tabanlı) kalkanı ölçer — LLM, GPU, "
        "ağ gerektirmez, her commit'te CI'da koşabilir. Gerçek-LLM gerektiren ölçümler "
        "(RAG faithfulness, full-pipeline kalite, prompt-injection çıktı kontrolü) ayrı "
        "harness'larda koşar (`quality_gate.py`, `ragas_full.py`, `policy_eval.py`).",
        "",
    ]
    return "\n".join(lines)


def render_console(sc: dict) -> str:
    hs = sc["hallucination_shield"]
    ft = sc["fabricated_threshold"]
    bar = "=" * 66
    mark = "✅" if sc["shield_pass"] else "❌"
    out = [
        f"\n{bar}",
        f"  ADALET YARIŞMA KARNESİ — {mark} {'GEÇTİ' if sc['shield_pass'] else 'KALDI'}  "
        f"(commit {sc['git_sha']})",
        bar,
        f"  Halüsinasyon kalkanı  : {hs['n']} vaka · P={hs['micro_precision']} "
        f"R={hs['micro_recall']} · yakalama={hs['hallucination_recall']:.0%}",
        f"  {mark} Yanlış-veto         : {hs['false_veto_count']}/{hs['n_clean']} "
        f"({hs['false_veto_rate']:.0%})  (hedef: 0 — iyi cevabı reddetme)",
        f"  FABRİKE-eşik          : {ft['n']} vaka · P={ft['precision']} "
        f"R={ft['recall']} F1={ft['f1']}",
        f"  %95 Wilson CI         : recall {hs['hallucination_recall_ci95']} · "
        f"FABRİKE-P {ft['precision_ci95']} · yanlış-veto oranı ≤ {hs['false_veto_rate_upper95']:.1%}",
        bar,
    ]
    return "\n".join(out)


def main(check_only: bool = False) -> int:
    sc = build_scorecard()
    print(render_console(sc))
    if not check_only:
        _DOC_OUT.parent.mkdir(parents=True, exist_ok=True)
        _DOC_OUT.write_text(render_markdown(sc), encoding="utf-8")
        print(f"  Jüri raporu -> {_DOC_OUT}")
        (_BACKEND / "eval" / "runs").mkdir(parents=True, exist_ok=True)
        (_BACKEND / "eval" / "runs" / "scorecard.json").write_text(
            json.dumps(sc, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if sc["shield_pass"] else 1


if __name__ == "__main__":
    import argparse
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="ADALET deterministik yarışma karnesi")
    ap.add_argument("--check", action="store_true", help="Yalnız PASS/FAIL (rapor yazma)")
    args = ap.parse_args()
    sys.exit(main(check_only=args.check))
