"""Kapsam-güven eval — ADALET yalnız 8 sivil hukuk alanında cevap versin (kapsam-dışı red).

Deterministik katmanı (LLM'siz, hızlı → her loop-iterasyonunda koşulur) ölçer:
  detect_smalltalk → _is_out_of_scope → _fast_domain sırası (triaj.py ile AYNI).
"uncertain" = keyword katmanı karar veremedi → DistilBERT/LLM'e kalır (ayrı, pahalı).

Metrikler (recall>precision: şüphedeyken reddet):
  - oos_caught:  alan-dışı sorunun keyword'le yakalanma oranı (yüksek iyi)
  - oos_leak:    alan-dışı → in_scope'a KAÇAN (kötü — saçma soru kabul edildi)
  - inscope_false_reject: gerçek sivil-hukuk → out_of_scope'a giden (kötü — iyi soru reddedildi)
  - smalltalk_ok: selamlaşma doğru tanındı mı (red EDİLMEMELİ)

Çalıştır: uv run python -m eval.scope_eval
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections import Counter
from pathlib import Path

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

GOLD = Path(__file__).parent.parent / "data" / "eval_benchmark" / "scope_gold.jsonl"


def predict(question: str) -> str:
    """Triaj keyword-katmanı tahmini (triaj.py sırasıyla birebir)."""
    from agents.nodes.triaj import _fast_domain, _is_out_of_scope
    from agents.smalltalk import detect_smalltalk

    if detect_smalltalk(question):
        return "smalltalk"
    if _is_out_of_scope(question):
        return "out_of_scope"
    if _fast_domain(question):
        return "in_scope"
    return "uncertain"  # DistilBERT/LLM kademesine kalır


def evaluate() -> dict:
    rows = [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_exp: dict[str, list] = {"out_of_scope": [], "smalltalk": [], "in_scope": []}
    for r in rows:
        r["pred"] = predict(r["soru"])
        by_exp[r["expected"]].append(r)

    oos = by_exp["out_of_scope"]
    oos_caught = sum(1 for r in oos if r["pred"] == "out_of_scope")
    oos_leak = sum(1 for r in oos if r["pred"] == "in_scope")
    oos_uncertain = sum(1 for r in oos if r["pred"] == "uncertain")

    insc = by_exp["in_scope"]
    insc_false_reject = sum(1 for r in insc if r["pred"] == "out_of_scope")
    insc_ok = sum(1 for r in insc if r["pred"] == "in_scope")

    st = by_exp["smalltalk"]
    st_ok = sum(1 for r in st if r["pred"] == "smalltalk")

    return {
        "n": len(rows),
        "oos_total": len(oos), "oos_caught": oos_caught, "oos_leak": oos_leak,
        "oos_uncertain": oos_uncertain,
        "insc_total": len(insc), "insc_ok": insc_ok, "insc_false_reject": insc_false_reject,
        "st_total": len(st), "st_ok": st_ok,
        "rows": rows,
    }


def main() -> int:
    res = evaluate()
    print(f"\n{'='*64}\n  KAPSAM-GÜVEN (keyword katmanı, deterministik)\n{'='*64}")
    print(f"  Alan-dışı yakalandı:    {res['oos_caught']}/{res['oos_total']}"
          f"   (uncertain={res['oos_uncertain']} → LLM'e kalır)")
    print(f"  ⚠️  Alan-dışı KAÇAN:     {res['oos_leak']}/{res['oos_total']}   (in_scope'a sızan = KÖTÜ)")
    print(f"  ⚠️  Gerçek-soru reddi:   {res['insc_false_reject']}/{res['insc_total']}   (false-rejection = KÖTÜ)")
    print(f"  Smalltalk doğru:        {res['st_ok']}/{res['st_total']}")
    print(f"  In-scope doğru:         {res['insc_ok']}/{res['insc_total']}")
    print()
    # Kaçanları ve yanlış-reddedilenleri listele (iterasyon hedefi)
    leaks = [r for r in res["rows"] if r["expected"] == "out_of_scope" and r["pred"] == "in_scope"]
    unc = [r for r in res["rows"] if r["expected"] == "out_of_scope" and r["pred"] == "uncertain"]
    frej = [r for r in res["rows"] if r["expected"] == "in_scope" and r["pred"] == "out_of_scope"]
    if leaks:
        print("  KAÇAN (alan-dışı→in_scope):")
        for r in leaks:
            print(f"    [{r['id']}] {r['soru'][:50]}")
    if unc:
        print("  UNCERTAIN (alan-dışı→LLM'e kalan):")
        for r in unc:
            print(f"    [{r['id']}] {r['soru'][:50]}")
    if frej:
        print("  YANLIŞ-RED (gerçek→out_of_scope):")
        for r in frej:
            print(f"    [{r['id']}] {r['soru'][:50]}")
    print(f"\n  dağılım: {dict(Counter(r['pred'] for r in res['rows']))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
