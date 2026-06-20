"""Quote-grounding (DRAFT_QUOTE_GROUNDING) A/B ölçümü — gerçek Qwen GPU, in-process.

Tek model yüklemesi; iki batch (baseline vs flag-ON) arası `os.environ` ile toggle
(is_quote_grounding_enabled call-time okur → tek süreçte çalışır). Stable env
(run-qwen-stable.sh): Qwen GPU, TÜM torch CPU (CUDA çatışma önlemi).

Çalıştır (stable env shell'den):
    SMOKE=1 uv run python -m eval.quote_grounding_ab   # 1 soru, hızlı doğrulama
    uv run python -m eval.quote_grounding_ab           # tam set

Metn: her soru için verdict, n_total/n_verified claim, grounded-oran, yanıt uzunluğu,
latency, [src:]/disclaimer var-mı. Hipotez: flag-ON → grounded-oran ↑ / halüsinasyon-red ↓,
latency+uzunluk kabul edilebilir.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict
from pathlib import Path

from agents.graph import build_graph
from agents.llm import reset_llm

# Windows: pyarrow'u torch'tan ÖNCE (access-violation guard) — torch dolaylı yüklenmeden önce.
from core import native_preload as _native_preload  # noqa: F401  (import sırası kritik)

_GOLD = Path("data/eval_benchmark/answer_cases.jsonl")


def _load_questions() -> list[str]:
    """Gold answer-cases'ten domain başına dengeli alt-set (EVAL_PER_DOMAIN, default 5).

    Yalnız expected_decision=='answer' (cevap-üreten yol; quote-grounding'i etkileyen).
    SMOKE=1 → ilk 1 soru (hızlı pipeline doğrulama). Gold yoksa eski sabit sete düşer.
    """
    if os.getenv("SMOKE", "0") in {"1", "true", "yes"}:
        return ["Kıdem tazminatına hak kazanmak için kaç yıl çalışılmalı?"]
    if not _GOLD.exists():
        return ["Kıdem tazminatına hak kazanmak için kaç yıl çalışılmalı?"]
    per = int(os.getenv("EVAL_PER_DOMAIN", "5"))
    by_dom: dict[str, list[str]] = defaultdict(list)
    for line in _GOLD.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("expected_decision") != "answer":
            continue
        by_dom[r.get("expected_domain", "?")].append(r["soru"])
    out: list[str] = []
    for dom in sorted(by_dom):
        out.extend(by_dom[dom][:per])
    return out


QUESTIONS: list[str] = _load_questions()


def _metrics(out: dict, dt: float) -> dict:
    resp = out.get("response", "") or ""
    claims = out.get("claims", []) or []
    verified = out.get("verified_claims", []) or claims
    n_total = len(claims)
    n_ver = len([c for c in verified if c.get("verified", False)])
    low = resp.lower()
    return {
        "verdict": out.get("debate_verdict", "?"),
        "n_total": n_total,
        "n_verified": n_ver,
        "grounded_ratio": round(n_ver / n_total, 3) if n_total else None,
        "resp_len": len(resp),
        "has_src": ("[src:" in resp) or any(c.get("cite_ids") for c in claims),
        "has_disclaimer": ("avukat" in low or "hukuki tavsiye" in low),
        "latency_s": round(dt, 1),
    }


async def _run_batch(label: str, questions: list[str]) -> list[dict]:
    reset_llm()  # env değişti → client'ı tazele
    graph = build_graph()
    rows: list[dict] = []
    for i, q in enumerate(questions, 1):
        t0 = time.monotonic()
        try:
            out = await graph.ainvoke({
                "question": q, "want_dilekce": False, "user_meta": {}, "retry_count": 0,
            })
            m = _metrics(out, time.monotonic() - t0)
        except Exception as exc:  # ölçüm scriptі — bir soru patlarsa diğerleri sürsün
            m = {"verdict": f"ERROR:{type(exc).__name__}", "latency_s": round(time.monotonic() - t0, 1)}
        m["q"] = q[:48]
        rows.append(m)
        print(f"[{label}] Q{i}: {m}", flush=True)
    return rows


def _aggregate(rows: list[dict]) -> dict:
    ok = [r for r in rows if isinstance(r.get("verdict"), str) and not r["verdict"].startswith("ERROR")]
    ratios = [r["grounded_ratio"] for r in ok if r.get("grounded_ratio") is not None]
    return {
        "n": len(rows),
        "pass": sum(1 for r in ok if r.get("verdict") == "pass"),
        "avg_grounded": round(sum(ratios) / len(ratios), 3) if ratios else None,
        "avg_verified": round(sum(r.get("n_verified", 0) for r in ok) / len(ok), 2) if ok else None,
        "avg_len": round(sum(r.get("resp_len", 0) for r in ok) / len(ok)) if ok else None,
        "avg_latency": round(sum(r.get("latency_s", 0) for r in ok) / len(ok), 1) if ok else None,
        "disclaimer_all": all(r.get("has_disclaimer") for r in ok) if ok else None,
    }


async def main() -> None:
    qs = QUESTIONS[:1] if os.getenv("SMOKE", "0") in {"1", "true", "yes"} else QUESTIONS
    print(f"== A/B quote-grounding | {len(qs)} soru | model={os.getenv('LLM_MODEL_PATH')} ==", flush=True)

    os.environ["DRAFT_QUOTE_GROUNDING"] = "0"
    base = await _run_batch("BASE", qs)

    os.environ["DRAFT_QUOTE_GROUNDING"] = "1"
    qg = await _run_batch("QG", qs)

    agg = {"baseline": _aggregate(base), "quote_grounding": _aggregate(qg)}
    print("\n== ÖZET ==", flush=True)
    print("BASELINE :", agg["baseline"], flush=True)
    print("QUOTE-GRD:", agg["quote_grounding"], flush=True)

    out_path = Path("eval/runs/quote_grounding_ab.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"summary": agg, "baseline_rows": base, "qg_rows": qg},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[yazıldı] {out_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
