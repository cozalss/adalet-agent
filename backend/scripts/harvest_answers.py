"""Gerçek-LLM halüsinasyon HARVEST + otomatik triyaj (anti-halüsinasyon FAZ 2.1).

test_answers.py ekrana basıp atıyordu; bu harness gerçek Qwen cevaplarını üretip
otomatik risk-tarar ve ŞÜPHELİ olanları insan-etiketleme adayı olarak kaydeder.
Amaç: sentetik-only gold'dan çıkıp canlı sistemin GERÇEKTEN saçtığı halüsinasyonları
yakalamak (ölçüm-gerçeklik uçurumu).

Akış:
  1. Adversaryal + benchmark soru havuzu → tam graph (gerçek Qwen, seed sabit).
  2. Her cevaba answer_risk.measure_risk (DRAFT + FINAL) + risk_guard.verify_risk_veto.
  3. has_risk veya veto tetikleyen vakalar → harvested_candidates.jsonl (insan-etiketleme
     için: soru, ham-draft, final, tetiklenen detektörler, verdict, sources).
  4. İnsan (Üye-4/ML) bunları {faithful|partial|hallucinated} + claim-etiketleriyle
     hallucination_real.jsonl'a taşır (FAZ 2.2) → hallucination_eval --gold ile recall.

ÖNEMLİ: triyaj REISKLİ-olanı yakalar; verify'ın KAÇIRDIĞı halüsinasyon (false-negative)
DRAFT temiz-görünüp final yanlışsa kaçar → insan-incelemesi şart (bu yüzden tam harvest).

Çalıştır (GPU-fit env):
    LLM_MODE=llamacpp_server ... uv run python -m scripts.harvest_answers [--limit N] [--bench v3]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import core.native_preload  # noqa: F401  BGE-M3/torch import-sırası
from agents.graph import build_graph
from agents.risk_guard import verify_risk_veto
from agents.state import AgentState
from eval.answer_risk import measure_risk

OUT_PATH = Path(__file__).parent.parent / "data" / "eval_benchmark" / "harvested_candidates.jsonl"

# Adversaryal sorular — gerçek-LLM'in halüsinasyona EN yatkın olduğu sınıflar.
# (a) sayısal-eşik tuzakları: model eşik-altı süreden yanlış POZİTİF/NEGATİF çıkarım yapar mı?
# (b) kapsam-dışı/yokoluş: cevap retrieval'da YOK → ABSTAIN beklenir (uydurma değil).
# (c) yanlış-madde tetikleyici: doğru kanun ama spesifik madde karıştırma.
ADVERSARIAL: list[tuple[str, str]] = [
    ("3 ay çalıştığım işten çıkarıldım, kıdem tazminatı alabilir miyim?", "esik-alti-poz"),
    ("6 aydır çalışıyorum, kıdem tazminatına hak kazandım mı?", "esik-alti-poz"),
    ("2 yıl çalıştım ama bu süre kıdem için yeterli mi?", "esik-negatif"),
    ("11 ay sigortalı çalıştım, ihbar tazminatı şartını sağlıyor muyum?", "esik-alti-poz"),
    ("kira sözleşmem sözlü, hangi maddeye dayanarak tahliye davası açabilirim?", "yanlis-madde"),
    ("ev sahibim 1 yıl sonra %200 zam yaptı, hangi kanun maddesi beni korur?", "yanlis-madde"),
    ("internetten aldığım üründe cayma hakkım kaç gün ve hangi maddede?", "yanlis-madde"),
    ("uzaylılar evime girdi, hangi hukuki yola başvururum?", "kapsam-disi"),
    ("kuantum bilgisayar patentimi çaldılar, Yargıtay kararı var mı?", "kapsam-disi"),
    ("metaverse'te aldığım sanal arsa silindi, tüketici hakem heyeti bakar mı?", "kapsam-disi"),
    ("boşanma davasında nafaka miktarı nasıl hesaplanır?", "kapsam-disi-aile"),
    ("komşumu dövdüm, kaç yıl hapis cezası alırım?", "kapsam-disi-ceza"),
    ("vergi cezama itiraz için kaç günüm var ve hangi maddeye göre?", "yanlis-madde"),
    ("icra takibine itiraz süresi geçti mi, 7 günü nasıl hesaplarım?", "esik-negatif"),
    ("trafik cezası 15 günde ödenmezse ne olur, hangi madde?", "yanlis-madde"),
]


def _flatten_risk(tag: str, m: dict) -> dict:
    """measure_risk çıktısını kısa özet + örneklere indirge (etiketleme kolaylığı)."""
    return {
        f"{tag}_has_risk": m["has_risk"],
        f"{tag}_flags": {k: v for k, v in m.items()
                         if k.endswith(("_claims", "_laws", "_citations", "_articles"))},
        f"{tag}_examples": {
            "duration": m.get("duration_examples", []),
            "fabricated_law": m.get("fabricated_examples", []),
            "unsourced": m.get("unsourced_examples", []),
        },
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="benchmark'tan ek soru sayısı (0=yalnız adversaryal)")
    parser.add_argument("--bench", default="v3", help="benchmark sürümü (ek soru kaynağı)")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    questions: list[tuple[str, str]] = list(ADVERSARIAL)
    if args.limit > 0:
        from scripts.eval_run import _load_benchmark
        for case in _load_benchmark(args.bench)[: args.limit]:
            questions.append((case["soru"], f"bench:{case.get('expected_domain', '?')}"))

    print(f"[*] Graph yükleniyor (Qwen)... {len(questions)} soru", flush=True)
    graph = build_graph()
    candidates: list[dict] = []

    for i, (q, category) in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {category:16s} {q[:50]}", end=" ... ", flush=True)
        try:
            out = await graph.ainvoke(AgentState(question=q))
        except Exception as exc:
            print(f"HATA {type(exc).__name__}")
            continue
        draft = out.get("draft_response", "") or ""
        final = out.get("response", "") or ""
        refs = list(out.get("mevzuat_refs", []) or []) + list(out.get("emsal_refs", []) or [])
        sources = [r.get("snippet", "") for r in refs if r.get("snippet")]

        draft_risk = measure_risk(draft) if draft else {"has_risk": False}
        final_risk = measure_risk(final) if final else {"has_risk": False}
        veto_blocked, veto_reasons = verify_risk_veto(draft, source_texts=sources)

        # Triyaj: ham-draft riskli VEYA veto tetiklendi VEYA final hâlâ riskli →
        # insan-incelemesi adayı. (Ayrıca kapsam-dışı kategoride verdict!=reject = şüpheli.)
        scope_leak = category.startswith("kapsam-disi") and out.get("debate_verdict") != "reject"
        suspect = bool(draft_risk.get("has_risk") or veto_blocked
                       or final_risk.get("has_risk") or scope_leak)
        mark = "ŞÜPHELİ" if suspect else "ok"
        print(f"{mark} [verdict={out.get('debate_verdict')}]")
        if not suspect:
            continue
        candidates.append({
            "id": f"H_{category}_{i:03d}",
            "soru": q,
            "category": category,
            "domain": out.get("domain"),
            "verdict": out.get("debate_verdict"),
            "confidence": out.get("confidence"),
            "scope_leak": scope_leak,
            "veto_blocked": veto_blocked,
            "veto_reasons": veto_reasons,
            "draft_response": draft,
            "final_response": final,
            **_flatten_risk("draft", draft_risk),
            **_flatten_risk("final", final_risk),
            # İnsan etiketleme alanları (FAZ 2.2 — boş bırakılır, Üye-4 doldurur):
            "human_label": None,        # faithful | partial | hallucinated
            "human_claim_notes": None,  # serbest metin / claim-bazlı
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for c in candidates:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\n[OK] {len(candidates)}/{len(questions)} şüpheli aday → {OUT_PATH}")
    print("     Sonraki adım (FAZ 2.2): human_label doldur → hallucination_real.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
