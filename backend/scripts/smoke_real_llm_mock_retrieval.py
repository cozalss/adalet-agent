"""Real-LLM + mock retrieval smoke — Sprint-4 W5 validation.

Qdrant olmadan, gerçek Qwen 14B Q4 ile agent graph'ı test eder:
  - Triage: gerçek LLM domain classification
  - Mevzuat/Emsal: fixture citations (Qdrant yerine)
  - Draft: gerçek LLM Türkçe cevap üretimi
  - Verify: 4-katmanlı doğrulama (rules + fuzzy + LettuceDetect + NLI)
  - Debate: gerçek LLM critique
  - Finalize: cevap + confidence

Çalıştırma:
  LLM_MODE=llamacpp_server LLM_SERVER_URL=http://127.0.0.1:8080 \
    uv run python -m scripts.smoke_real_llm_mock_retrieval
"""

from __future__ import annotations

import asyncio

# UTF-8 stdout (Windows console için)
import contextlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

os.environ.setdefault("LLM_MODE", "llamacpp_server")
os.environ.setdefault("LLM_SERVER_URL", "http://127.0.0.1:8080")
os.environ.setdefault("HYDE_ENABLED", "0")
os.environ.setdefault("MULTI_QUERY_ENABLED", "0")
os.environ.setdefault("LETTUCE_ENABLED", "0")
os.environ.setdefault("COLBERT_ENABLED", "0")
os.environ.setdefault("COLBERT_QUERY_ENABLED", "0")
os.environ.setdefault("RARR_ENABLED", "0")
os.environ.setdefault("PRELOAD_MODELS", "0")
os.environ.setdefault("NLI_FP16", "0")
os.environ.setdefault("MEVZUAT_DOMAIN_FILTER", "0")
os.environ.setdefault("PYTHONUTF8", "1")

# Fixture citations — gerçek mevzuat metni, Qdrant yok
SAMPLE_CITATIONS = {
    "isHukuku": [
        {
            "source_id": "m-IK-32", "doc_type": "law",
            "title": "4857 İK m.32",
            "snippet": (
                "İşveren, işçinin ücretini en geç ayda bir ödemekle yükümlüdür. "
                "Ücret en geç ödeme gününden itibaren yirmi gün içinde "
                "mücbir bir neden dışında ödenmezse işçi, iş görme borcunu "
                "yerine getirmekten kaçınabilir."
            ),
            "url": "https://mevzuat.gov.tr/IK/32", "score": 0.92,
        },
        {
            "source_id": "m-IK-14", "doc_type": "law",
            "title": "1475 İK m.14 Kıdem Tazminatı",
            "snippet": (
                "İşçinin işe başladığı tarihten itibaren iş sözleşmesinin "
                "devamı süresince her geçen tam yıl için işverence işçiye "
                "30 günlük ücreti tutarında kıdem tazminatı ödenir. "
                "Bir yıldan artan süreler için de aynı oran üzerinden ödeme yapılır. "
                "Kıdem tazminatına hak kazanmak için en az 1 yıl çalışılmış olmalıdır."
            ),
            "url": "https://mevzuat.gov.tr/IK/14", "score": 0.95,
        },
    ],
    "tuketici": [
        {
            "source_id": "m-TKHK-11", "doc_type": "law",
            "title": "6502 TKHK m.11",
            "snippet": (
                "Tüketici, ayıplı bir mal nedeniyle satıcıdan sözleşmeden dönmeyi, "
                "satış bedelinden indirim yapılmasını, ayıbın ücretsiz onarılmasını "
                "veya ayıpsız bir misli ile değiştirilmesini talep edebilir. "
                "Bu haklardan birini kullanma seçimi tüketiciye aittir."
            ),
            "url": "https://mevzuat.gov.tr/TKHK/11", "score": 0.94,
        },
        {
            "source_id": "m-TKHK-12", "doc_type": "law",
            "title": "6502 TKHK m.12",
            "snippet": (
                "Kanunlarda veya taraflar arasındaki sözleşmede daha uzun bir "
                "süre belirlenmediği takdirde, ayıplı maldan sorumluluk, "
                "ayıp daha sonra ortaya çıkmış olsa bile, malın tüketiciye "
                "teslim tarihinden itibaren iki yıllık zamanaşımına tabidir."
            ),
            "url": "https://mevzuat.gov.tr/TKHK/12", "score": 0.88,
        },
    ],
    "kira": [
        {
            "source_id": "m-TBK-315", "doc_type": "law",
            "title": "6098 TBK m.315",
            "snippet": (
                "Kiracı, kiralananın tesliminden sonra muaccel olan kira "
                "bedelini veya yan giderleri ödeme borcunu ifa etmezse, "
                "kiraya veren kiracıya yazılı olarak en az on günlük, "
                "konut ve çatılı işyeri kiralarında en az otuz günlük "
                "süre vererek borcun ifasını isteyebilir."
            ),
            "url": "https://mevzuat.gov.tr/TBK/315", "score": 0.91,
        },
    ],
}

SAMPLE_EMSAL = [
    {
        "source_id": "y-9HD-2019-1234", "doc_type": "case",
        "title": "Yargıtay 9.HD 2019/1234",
        "snippet": (
            "Davacı işçinin kıdem tazminatına hak kazanması için iş akdinin "
            "en az bir yıl sürmüş olması ve İş Kanunu m.14'te sayılan hallerden "
            "biri ile sona ermiş olması gerekir."
        ),
        "url": "https://karararama.yargitay.gov.tr/2019/1234", "score": 0.85,
    },
]


QUESTIONS = [
    ("E1", "Kıdem tazminatına hak kazanmak için ne kadar süre çalışılmalı?", "isHukuku"),
    ("E2", "Ayıplı mal aldım, hangi haklarım var?", "tuketici"),
    ("E3", "Kiracı kira ödemezse ne kadar süre ihtar verilir?", "kira"),
]


async def _smoke_one(graph, qid: str, question: str, expected_domain: str) -> dict:
    """Tek soruyu graph'tan geçir, metrikleri topla."""
    from agents import graph as graph_mod

    laws = SAMPLE_CITATIONS.get(expected_domain, SAMPLE_CITATIONS["isHukuku"])

    async def fake_mevzuat(_state):
        return {"mevzuat_refs": laws}

    async def fake_emsal(_state):
        return {"emsal_refs": SAMPLE_EMSAL if expected_domain == "isHukuku" else []}

    # graph_mod sembolleri monkeypatch (build-time import edilmiş kopya)
    orig_mevzuat = graph_mod.mevzuat_node
    orig_emsal = graph_mod.emsal_node
    graph_mod.mevzuat_node = fake_mevzuat
    graph_mod.emsal_node = fake_emsal

    try:
        # Graph'ı her seferinde yeniden build et (singleton purge)
        from agents.graph import build_graph
        g = build_graph()

        state = {
            "question": question,
            "want_dilekce": False,
            "user_meta": {},
            "retry_count": 0,
        }
        t0 = time.monotonic()
        out = await g.ainvoke(state)
        dt = time.monotonic() - t0
    finally:
        graph_mod.mevzuat_node = orig_mevzuat
        graph_mod.emsal_node = orig_emsal

    return {
        "qid": qid,
        "question": question,
        "expected_domain": expected_domain,
        "detected_domain": out.get("domain"),
        "verdict": out.get("debate_verdict"),
        "confidence": out.get("confidence"),
        "response_len": len(out.get("response", "")),
        "response_preview": out.get("response", "")[:400],
        "n_claims": len(out.get("claims", [])),
        "n_verified": sum(1 for c in out.get("verified_claims", []) if c.get("verified")),
        "latency_s": round(dt, 2),
        "has_disclaimer": "avukat" in out.get("response", "").lower() or "hukuki tavsiye" in out.get("response", "").lower(),
        "errors": out.get("errors", []),
    }


async def main() -> int:
    from agents.llm import reset_llm
    reset_llm()

    print(f"[smoke] Starting at {datetime.now().strftime('%H:%M:%S')}")
    print(f"[smoke] LLM_SERVER_URL = {os.environ.get('LLM_SERVER_URL')}")
    print(f"[smoke] LLM_MODE = {os.environ.get('LLM_MODE')}")
    print()

    results = []
    for qid, q, domain in QUESTIONS:
        print(f"[smoke] {qid} ({domain}): {q[:60]}...")
        try:
            r = await _smoke_one(None, qid, q, domain)
            results.append(r)
            print(f"  → {r['latency_s']}s, verdict={r['verdict']}, "
                  f"domain={r['detected_domain']}, "
                  f"verified={r['n_verified']}/{r['n_claims']}, "
                  f"len={r['response_len']}, "
                  f"disclaimer={r['has_disclaimer']}")
        except Exception as exc:
            print(f"  ✗ FAILED: {exc}")
            results.append({"qid": qid, "error": str(exc)})

    # Persist
    out_dir = Path("data/smoke_runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"smoke_real_llm_{ts}.json"
    out_path.write_text(
        json.dumps({"ts": ts, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[smoke] Report → {out_path}")

    # Summary
    n_pass = sum(1 for r in results if r.get("verdict") == "pass")
    n_reject = sum(1 for r in results if r.get("verdict") == "reject")
    n_retry = sum(1 for r in results if r.get("verdict") == "retry")
    avg_lat = sum(r.get("latency_s", 0) for r in results) / max(len(results), 1)
    print(f"\n[smoke] Summary: pass={n_pass}, retry={n_retry}, reject={n_reject}, "
          f"avg_lat={avg_lat:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
