"""Verify ON/OFF ablasyon harness'i — paper §4.2 (doğrulama etkinliği ölçümü).

Projenin TÜM tezi: "iddia-doğrulamalı = uydurmayan". Bu harness o iddiayı
SAYISAL olarak test eder: aynı soruları doğrulama katmanı AÇIK ve KAPALI iki
kez koşar, farkı ölçer.

  - ON  (VERIFY_ENABLED=1): 4-katman verify + debate kapısı çalışır.
  - OFF (VERIFY_ENABLED=0): verify TAMAMEN bypass (ham RAG-LLM; tüm iddialar
    sorgusuz "supported", verdict pass). `agents/nodes/verify.py` ablation
    kaldıracı.

Ölçülen "verify etkisi":
  - block_rate      : verify'ın OFF-pass'i ON'da reject/retry'a çevirme oranı
                      (= yakalanan şüpheli cevap oranı)
  - claim_support_Δ : ortalama (verified/total claim) ON vs OFF
  - dogrula_Δ       : [DOĞRULA: ...] placeholder farkı (CLAUDE.md halüsinasyon guard)
  - verdict dağılımı: ON ve OFF için pass/retry/reject sayıları

ÖNEMLİ — gerçek LLM şart: MockLLM canned cevap üretir → ON/OFF farkı anlamsız
olur. Anlamlı §4.2 tablosu için LLM_MODE=llamacpp_server (Qwen 14B GPU).
MockLLM ile koşum yalnız pipeline smoke'u (sayılar tez sonucu DEĞİLDİR).

Çalıştır:
    $env:LLM_MODE='llamacpp_server'
    uv run python -m eval.verify_ablation                 # default soru seti
    uv run python -m eval.verify_ablation --include-edge   # + edge_cases vakaları
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows: pyarrow'u torch'tan ÖNCE yükle (segfault guard).
from core import native_preload  # noqa: F401

# Helper + soru setini mevcut E2E harness'inden yeniden kullan (DRY).
from scripts.e2e_real_rag import (
    SAMPLE_QUESTIONS,
    _count_cjk,
    _count_dogrula_placeholders,
)


def _warm_retrieval_before_llm() -> None:
    """Embedder + reranker'ı LLM'den ÖNCE yükle (Windows native-init sırası).

    FlagEmbedding/torch, llama_cpp (Qwen) YÜKLENDİKTEN sonra ilk kez yüklenirse
    Windows'ta segfault (EXIT 139) oluyor — doğrulanmış E2E'de embedder preload
    ile Qwen'den önce yükleniyordu. Bu fonksiyon o sırayı garanti eder.
    EMBEDDING_DEVICE=cpu ile çağrılır (GPU'yu Qwen'e bırak → OOM yok).
    """
    with contextlib.suppress(Exception):
        from retrieval.embedding import Embedder
        Embedder().encode(["ısınma"], return_colbert=False)
    with contextlib.suppress(Exception):
        from retrieval.reranker import get_reranker
        _ = get_reranker()._model

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

_TRUTHY = {"1", "true", "yes"}


def _claim_support(state: dict) -> tuple[int, int]:
    """(verified_claim_sayısı, toplam_claim) — state['verified_claims']'ten."""
    vc = state.get("verified_claims") or []
    n_total = len(vc)
    n_verified = sum(1 for c in vc if c.get("verified"))
    return n_verified, n_total


async def _invoke(graph, question: str, verify_on: bool) -> dict:
    """Graph'ı verilen VERIFY_ENABLED durumuyla bir kez koştur.

    Flag call-time okunur (verify_node `os.getenv`) → aynı process içinde
    env'i flip edip iki kez koşmak güvenli.
    """
    from agents.graph import make_initial_state

    os.environ["VERIFY_ENABLED"] = "1" if verify_on else "0"
    state = make_initial_state(question)
    t0 = time.time()
    try:
        result = await graph.ainvoke(state)
        return {"ok": True, "elapsed_ms": int((time.time() - t0) * 1000), "result": result}
    except Exception as exc:
        # Harness: her vakayı izole et — tek soru patlarsa diğerleri koşsun.
        return {"ok": False, "elapsed_ms": int((time.time() - t0) * 1000),
                "result": None, "error": str(exc)}


def _summarize_arm(state: dict) -> dict:
    """Tek bir arm (ON veya OFF) için ölçüm satırı."""
    answer = state.get("response", "") or ""
    n_verified, n_total = _claim_support(state)
    return {
        "verdict": state.get("debate_verdict", "?"),
        "confidence": state.get("confidence", 0.0),
        "n_claims": n_total,
        "n_verified": n_verified,
        "support_ratio": round(n_verified / n_total, 3) if n_total else 0.0,
        "n_dogrula": _count_dogrula_placeholders(answer),
        "n_cjk": _count_cjk(answer),
        "answer_len": len(answer),
    }


async def _run_questions(graph, questions: list[tuple[str, str]]) -> list[dict]:
    """Her soru için ON + OFF koş, karşılaştırma satırı üret."""
    rows: list[dict] = []
    for qid, question in questions:
        print(f"\n[{qid}] {question}")
        on = await _invoke(graph, question, verify_on=True)
        off = await _invoke(graph, question, verify_on=False)
        if not (on["ok"] and off["ok"]):
            err = on.get("error") or off.get("error")
            print(f"  ✗ ERROR: {err}")
            rows.append({"id": qid, "question": question, "error": err})
            continue

        on_s = _summarize_arm(on["result"])
        off_s = _summarize_arm(off["result"])
        # verify "yakaladı" mı? OFF pass iken ON pass değil (reject/retry).
        blocked = off_s["verdict"] == "pass" and on_s["verdict"] != "pass"
        print(f"  ON : verdict={on_s['verdict']:<7s} support={on_s['support_ratio']:.0%} "
              f"DOĞRULA={on_s['n_dogrula']}")
        print(f"  OFF: verdict={off_s['verdict']:<7s} support={off_s['support_ratio']:.0%} "
              f"DOĞRULA={off_s['n_dogrula']}  {'← verify YAKALADI' if blocked else ''}")
        rows.append({
            "id": qid, "question": question,
            "on": on_s, "off": off_s, "verify_blocked": blocked,
            "elapsed_ms": {"on": on["elapsed_ms"], "off": off["elapsed_ms"]},
        })
    return rows


def _aggregate(rows: list[dict]) -> dict:
    """Satırlardan §4.2 özet metrikleri."""
    ok = [r for r in rows if "error" not in r]
    n = len(ok)
    if not n:
        return {"n": 0}
    blocked = sum(1 for r in ok if r["verify_blocked"])
    on_support = sum(r["on"]["support_ratio"] for r in ok) / n
    off_support = sum(r["off"]["support_ratio"] for r in ok) / n
    on_dogrula = sum(r["on"]["n_dogrula"] for r in ok)
    off_dogrula = sum(r["off"]["n_dogrula"] for r in ok)

    def _verdicts(arm: str) -> dict[str, int]:
        out = {"pass": 0, "retry": 0, "reject": 0}
        for r in ok:
            out[r[arm]["verdict"]] = out.get(r[arm]["verdict"], 0) + 1
        return out

    return {
        "n": n,
        "block_rate": round(blocked / n, 3),
        "n_blocked": blocked,
        "avg_support_on": round(on_support, 3),
        "avg_support_off": round(off_support, 3),
        "support_delta": round(off_support - on_support, 3),
        "total_dogrula_on": on_dogrula,
        "total_dogrula_off": off_dogrula,
        "verdicts_on": _verdicts("on"),
        "verdicts_off": _verdicts("off"),
    }


def _print_summary(agg: dict, out_path: Path) -> None:
    print("\n" + "=" * 72)
    print(" VERIFY ABLATION ÖZET (paper §4.2)")
    print("=" * 72)
    if not agg.get("n"):
        print("Başarılı koşum yok.")
        return
    print(f"Soru (başarılı)        : {agg['n']}")
    print(f"Verify block-rate      : {agg['block_rate']:.0%} "
          f"({agg['n_blocked']}/{agg['n']} OFF-pass → ON-block)")
    print(f"Ort. claim-support ON  : {agg['avg_support_on']:.0%}")
    print(f"Ort. claim-support OFF : {agg['avg_support_off']:.0%} "
          f"(Δ {agg['support_delta']:+.0%})")
    print(f"[DOĞRULA] ON / OFF     : {agg['total_dogrula_on']} / {agg['total_dogrula_off']}")
    print(f"Verdict ON             : {agg['verdicts_on']}")
    print(f"Verdict OFF            : {agg['verdicts_off']}")
    print(f"\nJSON: {out_path}")


def _load_questions(include_edge: bool) -> list[tuple[str, str]]:
    """Soru seti — E2E sample (8) + opsiyonel edge_cases adversarial vakalar."""
    questions = [(qid, q) for qid, q, _dom, _kw in SAMPLE_QUESTIONS]
    if include_edge:
        from eval.edge_cases import EDGE_CASES
        questions += [(c.id, c.question) for c in EDGE_CASES]
    return questions


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.verify_ablation")
    parser.add_argument("--include-edge", action="store_true",
                        help="edge_cases adversarial vakalarını da dahil et")
    args = parser.parse_args(argv)

    if os.environ.get("LLM_MODE", "mock") == "mock":
        print("[!] LLM_MODE=mock — MockLLM canned cevap verir; ON/OFF farkı")
        print("    ANLAMSIZdır (yalnız pipeline smoke). Gerçek §4.2 için:")
        print("    $env:LLM_MODE='llamacpp_server'  (Qwen 14B GPU)")

    os.environ.setdefault("HYDE_ENABLED", "0")  # ekstra LLM çağrısı, ablation'a gereksiz

    # Gerçek LLM modunda embedder/reranker'ı Qwen'den ÖNCE yükle (segfault guard).
    if os.environ.get("LLM_MODE", "mock") != "mock":
        _warm_retrieval_before_llm()

    from agents.graph import build_graph
    graph = build_graph()

    questions = _load_questions(args.include_edge)
    out_dir = Path("eval/runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"verify_ablation_{ts}.json"

    print("=" * 72)
    print(f" VERIFY ABLATION — {len(questions)} soru × 2 arm | "
          f"LLM={os.environ.get('LLM_MODE', 'mock')}")
    print("=" * 72)

    rows = await _run_questions(graph, questions)
    agg = _aggregate(rows)
    payload = {
        "meta": {
            "timestamp": ts,
            "llm_mode": os.environ.get("LLM_MODE", "mock"),
            "n_questions": len(questions),
            "include_edge": args.include_edge,
            "note": "MockLLM ise sayılar tez sonucu değildir (canned çıktı).",
        },
        "summary": agg,
        "rows": rows,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_summary(agg, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
