"""Reddedilen vakaların KÖK sebebini yakala — draft + risk-veto + NLI claim özeti.

is/icra/kira pass'ten reject'e düştü (2026-06-04 fix sonrası). risk_guard mı NLI mi?
Çalıştır (GPU-fit env): uv run python -m scripts.diag_reject
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.native_preload  # noqa: F401
from agents.graph import build_graph
from agents.risk_guard import verify_risk_veto
from agents.state import AgentState

CASES = [
    ("is", "5 yıldır çalıştığım işten tazminatsız çıkarıldım, kıdem ve ihbar tazminatı alabilir miyim?"),
    ("icra", "Hiç tanımadığım bir alacaklı hakkımda icra takibi başlattı, borcum yok, nasıl itiraz ederim?"),
    ("kira", "Ev sahibim kira sözleşmem bittiğinde depozitomu iade etmiyor, evi hasarsız teslim ettim, ne yapabilirim?"),
]


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    graph = build_graph()
    for dom, q in CASES:
        print("\n" + "=" * 90, flush=True)
        print(f"[{dom}] {q}", flush=True)
        out = await graph.ainvoke(AgentState(question=q))
        draft = out.get("draft_response") or ""
        claims = out.get("claims") or []
        verified = [c for c in claims if (c.get("verified") if isinstance(c, dict) else getattr(c, "verified", None))]
        unver = [c for c in claims if c not in verified]
        print(f"  verdict={out.get('debate_verdict')} · draft_len={len(draft)} · "
              f"claims={len(claims)} verified={len(verified)} unverified={len(unver)}", flush=True)
        blocked, reasons = verify_risk_veto(draft)
        print(f"  RISK-VETO: blocked={blocked} reasons={reasons}", flush=True)
        notes = out.get("debate_notes") or ""
        if notes:
            print(f"  debate_notes: {str(notes)[:200]}", flush=True)
        for c in unver[:4]:
            txt = c.get("text") if isinstance(c, dict) else getattr(c, "text", "")
            rsn = c.get("verify_reason") if isinstance(c, dict) else getattr(c, "verify_reason", "")
            print(f"    UNVERIFIED: {str(txt)[:90]} | {str(rsn)[:60]}", flush=True)
        print(f"  --- DRAFT ilk 700:\n  {draft[:700].replace(chr(10), chr(10)+'  ')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
