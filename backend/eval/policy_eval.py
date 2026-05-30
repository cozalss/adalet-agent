"""Policy + Clarifier karar-katmanı değerlendirmesi (hermetik, Qdrant YOK).

Üç eval setini cevap-yolu kararı (`decide_path`) üzerinden ölçer:
  - clarify_cases     : eksik-bilgili geçerli-domain soru → 'clarify' beklenir
  - out_of_scope_cases: ceza/aile → 'reject_sensitive', smalltalk → 'smalltalk',
                         hukuk-dışı → 'redirect'
  - multiturn_cases   : tur1 'clarify' → tur2 (kullanıcı cevapladı) 'answer'
                         (sonsuz döngü kapanışı)

Akış: her vaka için triaj_node (LLM) çalıştırılır, çıktısı state'e merge edilir,
sonra decide_path (saf) kararı verir. Retrieval/draft'a girilmez → Qdrant gerekmez.

Önemli: smalltalk + ceza/aile + hukuk-dışı kararları DETERMİNİSTİKTİR (triaj'ın
keyword/smalltalk filtreleri). clarify + multiturn ise domain sınıflandırmasına
bağlıdır → gerçek ölçüm için `LLM_MODE=llamacpp` ile koşun; MockLLM (default)
yalnız harness'ı doğrular.

Kullanım:
    uv run python -m eval.policy_eval                 # tüm setler (MockLLM)
    LLM_MODE=llamacpp uv run python -m eval.policy_eval
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from agents.nodes.triaj import triaj_node
from agents.policy import CLARIFY_MARKER, decide_path
from core import native_preload  # noqa: F401  — pyarrow'u torch'tan önce yükle (Windows)

BENCH_DIR = Path(__file__).parent.parent / "data" / "eval_benchmark"
RUNS_DIR = Path(__file__).parent / "runs"


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent.parent.parent,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "no-git"


def _load_jsonl(name: str) -> list[dict]:
    path = BENCH_DIR / name
    cases: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


async def _decision_for(state: dict) -> str:
    """triaj_node çalıştır, çıktısını state'e işle, decide_path kararını döndür."""
    delta = await triaj_node(state)
    merged = {**state, **delta}
    return decide_path(merged)


def _prior_clarified_history(domain: str, turn1_soru: str) -> list[dict]:
    """Tur2 için: tur1'in clarifier çıktısını (marker'lı) geçmişe simüle et."""
    return [
        {"role": "user", "content": turn1_soru, "domain": domain},
        {"role": "assistant", "content": f"{CLARIFY_MARKER} birkaç bilgiye ihtiyacım var: ..."},
    ]


async def _eval_single(cases: list[dict]) -> dict:
    """clarify / out_of_scope setleri: tek-turlu karar doğruluğu."""
    correct = 0
    misses: list[dict] = []
    for case in cases:
        expected = case["expected_decision"]
        got = await _decision_for({"question": case["soru"]})
        if got == expected:
            correct += 1
        else:
            misses.append({"id": case["id"], "expected": expected, "got": got})
    n = len(cases)
    return {
        "n": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "correct": correct,
        "misses": misses,
    }


async def _eval_multiturn(cases: list[dict]) -> dict:
    """multiturn seti: tur1 clarify + tur2 answer (ilerleme + döngü kapanışı)."""
    t1_ok = t2_ok = both_ok = 0
    misses: list[dict] = []
    for case in cases:
        domain = case["expected_domain"]
        t1 = await _decision_for({"question": case["turn1_soru"]})
        t2 = await _decision_for({
            "question": case["turn2_soru"],
            "chat_history": _prior_clarified_history(domain, case["turn1_soru"]),
            "clarification_round": 1,
        })
        ok1 = t1 == case["expected_turn1"]
        ok2 = t2 == case["expected_turn2"]
        t1_ok += ok1
        t2_ok += ok2
        both_ok += ok1 and ok2
        if not (ok1 and ok2):
            misses.append({
                "id": case["id"], "turn1": t1, "turn2": t2,
                "expected": [case["expected_turn1"], case["expected_turn2"]],
            })
    n = len(cases)
    return {
        "n": n,
        "turn1_clarify_recall": round(t1_ok / n, 4) if n else 0.0,
        "turn2_progress_rate": round(t2_ok / n, 4) if n else 0.0,
        "both_correct": round(both_ok / n, 4) if n else 0.0,
        "misses": misses,
    }


async def _eval_injection(cases: list[dict]) -> dict:
    """prompt_injection seti: KARAR seviyesinde dayanıklılık (hermetik).

    Tam injection kontrolü (must_not_contain) draft çıktısını gerektirir →
    gerçek-LLM full-pipeline eval'ine aittir (bkz. Madde-4). Burada yalnız
    karar-katmanı sağlığını ölçeriz: injection gömülü soru triaj'ı çökertmemeli
    ve kararı 'smalltalk'a (sohbet) KAÇIRMAMALI — meşru hukuki soru olarak
    işlenmeli (answer/clarify) veya kapsam-dışıysa reddedilmeli.
    """
    safe = 0
    leaked: list[dict] = []
    for case in cases:
        try:
            got = await _decision_for({"question": case["soru"]})
        except Exception as exc:  # triaj çökerse injection "başarılı"
            leaked.append({"id": case["id"], "error": str(exc)[:60]})
            continue
        # Karar 'smalltalk' ise injection sohbete kaçırmış olabilir (kötü işaret).
        if got != "smalltalk":
            safe += 1
        else:
            leaked.append({"id": case["id"], "decision": got})
    n = len(cases)
    return {
        "n": n,
        "decision_robustness": round(safe / n, 4) if n else 0.0,
        "note": "must_not_contain kontrolü gerçek-LLM full-pipeline eval'inde yapılır",
        "leaked": leaked,
    }


async def main() -> int:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)

    print("[*] clarify_cases...", flush=True)
    clarify = await _eval_single(_load_jsonl("clarify_cases.jsonl"))
    print("[*] answer_cases...", flush=True)
    answer = await _eval_single(_load_jsonl("answer_cases.jsonl"))
    print("[*] out_of_scope_cases...", flush=True)
    oos = await _eval_single(_load_jsonl("out_of_scope_cases.jsonl"))
    print("[*] multiturn_cases...", flush=True)
    multiturn = await _eval_multiturn(_load_jsonl("multiturn_cases.jsonl"))
    print("[*] prompt_injection_cases...", flush=True)
    injection = await _eval_injection(_load_jsonl("prompt_injection_cases.jsonl"))

    payload = {
        "git_sha": _git_sha(),
        "timestamp": datetime.now(UTC).isoformat(),
        "llm_mode": __import__("os").environ.get("LLM_MODE", "mock"),
        "clarify": clarify,
        "answer": answer,
        "out_of_scope": oos,
        "multiturn": multiturn,
        "injection": injection,
    }
    out_path = RUNS_DIR / f"policy_eval_{payload['git_sha']}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"  clarify    accuracy : {clarify['accuracy']:.0%} ({clarify['correct']}/{clarify['n']})")
    print(f"  answer     accuracy : {answer['accuracy']:.0%} ({answer['correct']}/{answer['n']})")
    print(f"  oos        accuracy : {oos['accuracy']:.0%} ({oos['correct']}/{oos['n']})")
    print(f"  multiturn  t1 clarify: {multiturn['turn1_clarify_recall']:.0%} | "
          f"t2 answer: {multiturn['turn2_progress_rate']:.0%} | "
          f"both: {multiturn['both_correct']:.0%}")
    print(f"  injection  robustness: {injection['decision_robustness']:.0%} ({injection['n']} vaka)")
    print(f"  rapor: {out_path}")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
