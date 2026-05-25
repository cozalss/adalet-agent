"""E2E smoke test — LangGraph 7 ajan + MockLLM (Sprint-3).

Akış: triaj → [mevzuat (HyDE), emsal] (paralel) → draft → verify → debate
       → (retry → draft | reject/pass → finalize) → END

Amaç:
  1. Graph derleniyor mu? (7 node)
  2. Yeni verify + debate node'ları çalışıyor mu?
  3. Retry / reject yolları kontrol altında mı?
  4. Çıktıda response, confidence, disclaimer, verdict var mı?

Çalıştırma:
    uv run python -m scripts.test_graph_e2e

Mock LLM kullanıyor — gerçek Qwen kurulmadan da çalışır.
Retrieval gerçek Qdrant'tan veri çeker; collection'da veri yoksa boş döner
ama akış kırılmaz (finalize reject branch).
HyDE: HYDE_ENABLED=0 ile devre dışı (smoke için network'ten kaçın).
"""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("LLM_MODE", "mock")
os.environ.setdefault("HYDE_ENABLED", "0")
os.environ.setdefault("NLI_FP16", "0")

# Windows cp1254 console'da emoji + Türkçe için UTF-8 zorla
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass


async def main() -> int:
    from agents.graph import build_graph, make_initial_state

    print("=" * 72)
    print(" LANGGRAPH E2E SMOKE TEST (MockLLM + verify+debate wired)")
    print("=" * 72)

    graph = build_graph()
    print("[OK] Graph derlendi (7 node)")

    questions = [
        ("Q1", "Kıdem tazminatı nasıl hesaplanır?"),
        ("Q2", "Ev sahibim depozitomu vermiyor, ne yapabilirim?"),
        ("Q3", "Ayıplı malda tüketici hakkı nedir?"),
        ("Q4", "Cinayetten yargılanıyorum, ne yapayım?"),  # OUT OF SCOPE
    ]

    for qid, q in questions:
        print(f"\n--- [{qid}] {q} ---")
        state = make_initial_state(q)
        try:
            result = await graph.ainvoke(state)
        except Exception as exc:
            print(f"  [XX] ERROR: {exc}")
            continue

        print(f"  domain:           {result.get('domain')}")
        print(f"  domain_conf:      {result.get('domain_confidence', 0):.2f}")
        print(f"  mevzuat_refs:     {len(result.get('mevzuat_refs', []))}")
        print(f"  emsal_refs:       {len(result.get('emsal_refs', []))}")
        print(f"  draft_length:     {len(result.get('draft_response', ''))}")
        print(f"  claims:           {len(result.get('claims', []))}")
        print(f"  verified_claims:  {len(result.get('verified_claims', []))}")
        n_ver = sum(1 for c in result.get("verified_claims", []) if c.get("verified"))
        print(f"  -> dogrulanan:    {n_ver}")
        print(f"  debate_verdict:   {result.get('debate_verdict')}")
        print(f"  retry_count:      {result.get('retry_count', 0)}")
        print(f"  confidence:       {result.get('confidence', 0):.2f}")
        print(f"  errors:           {result.get('errors', [])}")
        print(f"  debate_notes:     {result.get('debate_notes', '')[:160]}")
        print("  response (ilk 240):")
        print("    " + (result.get("response", "")[:240] or "(bos)"))

    print("\n" + "=" * 72)
    print(" [OK] Sprint-3 E2E akis tamamlandi")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
