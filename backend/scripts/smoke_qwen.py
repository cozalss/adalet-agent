"""İlk gerçek LLM smoke testi — Qwen 2.5 14B Q4_K_M GGUF, CPU.

CLAUDE.md §3 production-policy: OpenAI/Anthropic API YOK, lokal Qwen.
Bu script:
  1. LlamaCppClient'ı yükler (~30-60 sn CPU init)
  2. Türkçe hukuk sistem prompt'u ile bir cevap ister
  3. JSON-mode triaj prompt'u ile JSON cevap ister
  4. Latans + token sayılarını raporlar

Çalıştırma (CUDA wheel önerilir; CPU smoke için):
    set LLM_MODE=llamacpp
    set LLM_MODEL_PATH=C:\\Users\\cemmo\\models\\Qwen2.5-14B-Instruct-Q4_K_M.gguf
    .venv\\Scripts\\python.exe scripts/smoke_qwen.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


async def smoke_chat() -> None:
    from agents.llm import ChatMessage, get_llm, reset_llm

    reset_llm()
    os.environ["LLM_MODE"] = "llamacpp"
    if "LLM_MODEL_PATH" not in os.environ:
        default = r"C:\Users\cemmo\models\Qwen2.5-14B-Instruct-Q4_K_M.gguf"
        os.environ["LLM_MODEL_PATH"] = default

    print("=" * 70)
    print(" QWEN 2.5 14B Q4_K_M — SMOKE TEST")
    print("=" * 70)
    print(f"Model: {os.environ['LLM_MODEL_PATH']}")

    llm = get_llm()

    # --- Test 1: Türkçe hukuk free-text ---
    print("\n[1/2] Türkçe hukuk soru → free-text yanıt")
    t0 = time.time()
    resp = await llm.chat(
        messages=[
            ChatMessage(
                role="system",
                content=(
                    "Sen Türk hukuku alanında uzman bir asistansın. "
                    "Cevap kısa, açık ve madde-numaralı olsun."
                ),
            ),
            ChatMessage(
                role="user",
                content="Tüketici, ayıplı bir maldan dolayı hangi hakları kullanabilir? "
                        "Lütfen Tüketicinin Korunması Hakkında Kanun (6502) açısından özetle.",
            ),
        ],
        temperature=0.1,
        max_tokens=300,
        json_mode=False,
    )
    dt = time.time() - t0
    print(f"  latency : {dt:.1f}s")
    print(f"  tokens  : in={resp.tokens_in} out={resp.tokens_out}")
    print(f"  finish  : {resp.finish_reason}")
    print(f"  content :\n{resp.content[:500]}")

    # --- Test 2: JSON mode triaj ---
    print("\n[2/2] JSON mode triaj domain sınıflandırma")
    t0 = time.time()
    resp2 = await llm.chat(
        messages=[
            ChatMessage(
                role="system",
                content=(
                    'Sen bir hukuk soru sınıflandırıcısın. SADECE JSON döndür: '
                    '{"domain": "tuketici"|"isHukuku"|"kira"|"icra"|"trafik"|'
                    '"vergi"|"tapu"|"idari"|"unknown", "confidence": 0.0..1.0, '
                    '"reasoning": "..."}'
                ),
            ),
            ChatMessage(role="user", content="Kıdem tazminatım nasıl hesaplanır?"),
        ],
        temperature=0.0,
        max_tokens=120,
        json_mode=True,
    )
    dt = time.time() - t0
    print(f"  latency : {dt:.1f}s")
    print(f"  tokens  : in={resp2.tokens_in} out={resp2.tokens_out}")
    print(f"  content : {resp2.content[:200]}")

    print("\n[OK] Smoke test tamam.")


if __name__ == "__main__":
    asyncio.run(smoke_chat())
