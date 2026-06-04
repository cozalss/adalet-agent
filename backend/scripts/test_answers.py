"""Konuşma KALİTESİ testi — birkaç soruyu full graph (gerçek Qwen) ile koşup TAM cevapları yazar.

Ölçüm-sürücülü konuşma iyileştirmesi: gerçek cevapları GÖR → prompt'u iyileştir → re-test.
GPU-fit in-process LLM gerekir (run-local-demo env). e2e_real_rag 300-char kesiyor; bu TAM yazar.

Çalıştır (GPU-fit env ile):
    LLM_MODE=llamacpp LLM_SPECULATIVE=0 ... uv run python -m scripts.test_answers
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.native_preload  # noqa: F401  BGE-M3/torch import-sırası
from agents.graph import build_graph
from agents.state import AgentState

QUESTIONS = [
    "Ev sahibim depozitomu geri vermiyor, ne yapabilirim?",            # kira (legal)
    "2 yıl çalıştığım işten haksız çıkarıldım, kıdem tazminatı alabilir miyim?",  # iş (legal)
    "İnternetten aldığım telefon bozuk çıktı, ne yapabilirim?",        # tüketici (legal)
    "merhaba, sen kimsin ve bana nasıl yardımcı olabilirsin?",        # smalltalk → chat
]


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("[*] Graph yukleniyor (Qwen GPU)...", flush=True)
    graph = build_graph()
    for q in QUESTIONS:
        print("\n" + "=" * 90, flush=True)
        print(f"SORU: {q}", flush=True)
        try:
            out = await graph.ainvoke(AgentState(question=q))
        except Exception as exc:
            print(f"  HATA: {type(exc).__name__}: {exc}", flush=True)
            continue
        print(f"[domain={out.get('domain')} · verdict={out.get('debate_verdict')} · "
              f"intent={out.get('response_intent')} · conf={out.get('confidence')} · "
              f"refs={len(out.get('mevzuat_refs', []) or []) + len(out.get('emsal_refs', []) or [])}]",
              flush=True)
        print("-" * 40 + " CEVAP:", flush=True)
        print(out.get("response", "(boş)"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
