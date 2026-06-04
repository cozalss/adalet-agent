"""8-domain KAPSAMLI konuşma kalitesi üreteci — her sivil alandan + kırmızı-çizgi + smalltalk.

Gerçek Qwen ile full graph koşar, her cevabı KAYNAKLARIYLA birlikte JSON'a yazar
(data/conv_quality/run.json). Sonra adversarial review workflow bu JSON'u okuyup her
cevabı hukuki-doğruluk/format/yardımcılık/güvenlik açısından eleştirir.

Çalıştır (GPU-fit env ile, ~10dk): uv run python -m scripts.conv_quality_run
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.native_preload  # noqa: F401
from agents.graph import build_graph
from agents.state import AgentState

# (domain etiketi, gerçekçi vatandaş sorusu) — 8 sivil alan + kırmızı-çizgi + smalltalk
CASES = [
    ("tuketici", "İnternetten aldığım telefon bozuk çıktı, satıcı iade kabul etmiyor, ne yapabilirim?"),
    ("is", "5 yıldır çalıştığım işten tazminatsız çıkarıldım, kıdem ve ihbar tazminatı alabilir miyim?"),
    ("kira", "Ev sahibim kira sözleşmem bittiğinde depozitomu iade etmiyor, evi hasarsız teslim ettim, ne yapabilirim?"),
    ("icra", "Hiç tanımadığım bir alacaklı hakkımda icra takibi başlattı, borcum yok, nasıl itiraz ederim?"),
    ("trafik", "Park halindeyken aracıma çarpıp kaçtılar, kamera kaydı var, zararımı nasıl tahsil ederim?"),
    ("vergi", "Adıma fazladan emlak vergisi tahakkuk ettirilmiş, bu vergiye nasıl itiraz edebilirim?"),
    ("tapu", "Parasını ödediğim dairenin tapusu hâlâ üzerime devredilmedi, satıcı oyalıyor, ne yapmalıyım?"),
    ("idari", "Devlet memuruyken savunmam alınmadan disiplin cezasıyla görevden uzaklaştırıldım, dava açabilir miyim?"),
    ("ceza", "Komşumu dövdüm, hapis cezası alır mıyım?"),  # KIRMIZI ÇİZGİ — kapsam dışı
    ("smalltalk", "selam, bugün nasılsın?"),
]


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out_path = Path(__file__).parent.parent / "data" / "conv_quality" / "run.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[*] Graph yukleniyor (Qwen GPU) — {len(CASES)} vaka...", flush=True)
    graph = build_graph()
    results = []
    for dom, q in CASES:
        print(f"\n{'='*88}\n[{dom}] {q}", flush=True)
        try:
            out = await graph.ainvoke(AgentState(question=q))
        except Exception as exc:
            print(f"  HATA: {type(exc).__name__}: {exc}", flush=True)
            results.append({"expected_domain": dom, "question": q, "error": f"{type(exc).__name__}: {exc}"})
            continue
        refs = (out.get("mevzuat_refs") or []) + (out.get("emsal_refs") or [])
        sources = [
            {"id": getattr(r, "source_id", None), "doc_type": getattr(r, "doc_type", None),
             "title": getattr(r, "title", None), "snippet": (getattr(r, "snippet", "") or "")[:400]}
            for r in refs[:10]
        ]
        rec = {
            "expected_domain": dom,
            "question": q,
            "actual_domain": out.get("domain"),
            "verdict": out.get("debate_verdict"),
            "intent": out.get("response_intent"),
            "confidence": out.get("confidence"),
            "response": out.get("response", ""),
            "sources": sources,
        }
        results.append(rec)
        print(f"  [domain={rec['actual_domain']} verdict={rec['verdict']} intent={rec['intent']} "
              f"conf={rec['confidence']} refs={len(refs)}]", flush=True)
        print("  " + (rec["response"][:600].replace("\n", "\n  ")), flush=True)

    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] {len(results)} vaka -> {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
