"""Gerçek RAG E2E — Qdrant + llama-server + tüm graph node'ları.

CLAUDE.md §3 sıfır-halüsinasyon iddiasını GERÇEK LLM ile test eder. MockLLM
ölçümleri anlamsızdı; bu script Qwen 2.5 14B GPU çıkarımıyla:

  1. 8 örnek soru çek (her domain'den)
  2. Her soru için build_graph() ile uçtan-uca ainvoke
  3. Topla:
     - latency (ms)
     - domain doğruluğu (benchmark expected vs actual)
     - mevzuat_refs count + top_score
     - emsal_refs count
     - debate verdict (pass/retry/reject)
     - response uzunluğu + ilk 300 char
     - varsa "[DOĞRULA:" placeholder sayısı (hallucination proxy)
     - varsa Çince karakter leak sayısı (Qwen 14B Q4 quantization artifact)
  4. data/e2e_runs/<timestamp>.jsonl olarak yaz
  5. Ekrana özet tablosu

Önkoşul:
  - Qdrant + Redis container ayakta (docker compose up -d)
  - llama-server.exe çalışıyor: http://127.0.0.1:8080
  - export LLM_MODE=llamacpp_server

Çalıştır:
  uv run python -m scripts.e2e_real_rag
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# Sample sorular — her domain'den 1, çeşitlilik için ek
SAMPLE_QUESTIONS = [
    # (id, soru, expected_domain, expected_keywords)
    ("E1", "Kıdem tazminatı nasıl hesaplanır?", "isHukuku",
     ["kıdem", "30 günlük", "her yıl"]),
    ("E2", "İhbar tazminatı süreleri nelerdir?", "isHukuku",
     ["ihbar", "6 hafta", "altı"]),
    ("E3", "Ayıplı malda tüketici hangi haklara sahiptir?", "tuketici",
     ["ayıplı", "iade", "değişim", "TKHK"]),
    ("E4", "Ev sahibi kira sözleşmesini hangi sebeplerle feshedebilir?", "kira",
     ["tahliye", "TBK", "ihtar", "fesih"]),
    ("E5", "Trafik kazasında sigorta tazminatı nasıl alınır?", "trafik",
     ["trafik sigortası", "ZMSS", "tazminat"]),
    ("E6", "İcra takibine itiraz nasıl yapılır?", "icra",
     ["icra", "itiraz", "İİK", "7 gün"]),
    ("E7", "Vergi cezasına itiraz süresi nedir?", "vergi",
     ["VUK", "uzlaşma", "30 gün", "vergi"]),
    ("E8", "Kat malikleri toplantısı nasıl yapılır?", "tapu",
     ["kat mülkiyeti", "KMK", "toplantı", "çoğunluk"]),
]


def _count_cjk(text: str) -> int:
    """Çince/Japonca/Korece karakter sayısı — Qwen quantization leak proxy'si."""
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def _count_dogrula_placeholders(text: str) -> int:
    """`[DOĞRULA: ...]` placeholder'ları (CLAUDE.md kuralı)."""
    return len(re.findall(r"\[DO[ĞG]RULA:", text, flags=re.IGNORECASE))


def _keyword_coverage(answer: str, keywords: list[str]) -> float:
    """Yanıtta beklenen anahtar kelimelerin oranı (case-insensitive)."""
    if not keywords:
        return 0.0
    al = answer.lower()
    hits = sum(1 for kw in keywords if kw.lower() in al)
    return hits / len(keywords)


async def run_one(graph, question: str) -> dict:
    """Tek soruyu graph'a sok, sonuçları topla."""
    from agents.graph import make_initial_state

    state = make_initial_state(question)
    t0 = time.time()
    try:
        result = await graph.ainvoke(state)
        elapsed_ms = int((time.time() - t0) * 1000)
        return {"ok": True, "elapsed_ms": elapsed_ms, "result": result, "error": None}
    except Exception as exc:
        elapsed_ms = int((time.time() - t0) * 1000)
        return {"ok": False, "elapsed_ms": elapsed_ms, "result": None, "error": str(exc)}


async def main() -> int:
    # Env kontrol
    if os.environ.get("LLM_MODE") not in {"llamacpp_server", "llama_server", "server"}:
        print("[!] LLM_MODE=llamacpp_server set edilmedi — MockLLM ile koşacak.")
        print("    Önce: $env:LLM_MODE='llamacpp_server'  (PowerShell)")
        print("    Veya: LLM_MODE=llamacpp_server uv run python -m scripts.e2e_real_rag")

    # llama-server sağlık (sessiz fallback)
    server_ok = False
    if os.environ.get("LLM_MODE", "").startswith(("llamacpp_server", "llama_server", "server")):
        import httpx
        url = os.environ.get("LLM_SERVER_URL", "http://127.0.0.1:8080")
        try:
            r = httpx.get(f"{url}/health", timeout=2.0)
            server_ok = r.status_code == 200
        except Exception:
            server_ok = False
        if not server_ok:
            print(f"[XX] llama-server ulaşılamadı: {url}/health")
            return 2

    # HyDE'ı kapat — ekstra LLM çağrısı zaman alır, smoke için odak ana akışta
    os.environ.setdefault("HYDE_ENABLED", "0")

    from agents.graph import build_graph
    graph = build_graph()

    out_dir = Path("data/e2e_runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"e2e_{ts}.jsonl"

    print("=" * 72)
    print(f" GERÇEK RAG E2E — {len(SAMPLE_QUESTIONS)} soru | LLM={os.environ.get('LLM_MODE', 'mock')}")
    print(f" llama-server: {'✓ ok' if server_ok else '✗ (mock fallback)'}")
    print(f" Output: {out_path}")
    print("=" * 72)

    rows: list[dict] = []
    domain_correct = 0
    pass_count = 0
    reject_count = 0
    total_cjk = 0
    total_dogrula = 0
    total_latency = 0
    total_keyword_cov = 0.0

    with out_path.open("w", encoding="utf-8") as fh:
        for qid, question, exp_domain, exp_keywords in SAMPLE_QUESTIONS:
            print(f"\n[{qid}] {question}")
            run = await run_one(graph, question)
            if not run["ok"]:
                print(f"  ✗ ERROR: {run['error']}")
                row = {
                    "id": qid, "question": question,
                    "expected_domain": exp_domain,
                    "error": run["error"], "elapsed_ms": run["elapsed_ms"],
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows.append(row)
                continue

            r = run["result"]
            answer = r.get("response", "")
            actual_domain = r.get("domain", "unknown")
            verdict = r.get("debate_verdict", "?")
            mev = r.get("mevzuat_refs") or []
            ems = r.get("emsal_refs") or []
            cite_count = len(mev) + len(ems)
            top_score = max([c.get("score", 0.0) for c in mev + ems], default=0.0)
            n_cjk = _count_cjk(answer)
            n_dogrula = _count_dogrula_placeholders(answer)
            kw_cov = _keyword_coverage(answer, exp_keywords)
            confidence = r.get("confidence", 0.0)

            domain_correct += int(actual_domain == exp_domain)
            pass_count += int(verdict == "pass")
            reject_count += int(verdict == "reject")
            total_cjk += n_cjk
            total_dogrula += n_dogrula
            total_latency += run["elapsed_ms"]
            total_keyword_cov += kw_cov

            print(f"  → {run['elapsed_ms']:>5}ms | dom={actual_domain:<10s} verdict={verdict:<7s} "
                  f"refs={cite_count} top={top_score:.2f} conf={confidence:.2f}")
            print(f"    kw_cov={kw_cov:.0%} CJK={n_cjk} DOĞRULA={n_dogrula}")
            print(f"    {answer[:200].strip()}...")

            row = {
                "id": qid,
                "question": question,
                "expected_domain": exp_domain,
                "actual_domain": actual_domain,
                "domain_correct": actual_domain == exp_domain,
                "verdict": verdict,
                "confidence": confidence,
                "elapsed_ms": run["elapsed_ms"],
                "n_mevzuat_refs": len(mev),
                "n_emsal_refs": len(ems),
                "top_score": top_score,
                "answer": answer,
                "keyword_coverage": kw_cov,
                "n_cjk_chars": n_cjk,
                "n_dogrula_placeholders": n_dogrula,
                "mevzuat_titles": [c.get("title") for c in mev[:5]],
                "emsal_titles": [c.get("title") for c in ems[:5]],
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows.append(row)

    n = max(1, sum(1 for r in rows if "error" not in r))
    print("\n" + "=" * 72)
    print(" ÖZET")
    print("=" * 72)
    print(f"Toplam soru        : {len(SAMPLE_QUESTIONS)}")
    print(f"Başarılı koşum     : {n}")
    print(f"Domain doğru       : {domain_correct}/{n} ({100*domain_correct/n:.0f}%)")
    print(f"Verdict pass       : {pass_count}/{n}")
    print(f"Verdict reject     : {reject_count}/{n}")
    print(f"Ortalama latans    : {total_latency / n:.0f} ms")
    print(f"Ort. keyword cov.  : {100*total_keyword_cov/n:.0f}%")
    print(f"Toplam CJK leak    : {total_cjk} char (Qwen quantization artifact)")
    print(f"[DOĞRULA] toplam   : {total_dogrula} (hallucination guard hit)")
    print(f"\nJSONL: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
