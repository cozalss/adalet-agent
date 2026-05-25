"""E2E ama HTTP üzerinden — uvicorn /ask endpoint'ine soru sırayla gönderir.

Daha stabil çünkü:
  - LangGraph + Embedder + Reranker UVICORN PROCESS içinde tek kez yüklenir
  - Her HTTP çağrı sadece istek/cevap
  - Process-level hang yok; her soru bağımsız
  - Output deterministik (HTTP response body)

Çalıştırmadan önce uvicorn çalışmalı:
  HF_HUB_OFFLINE=1 LLM_MODE=llamacpp_server uv run uvicorn main:app
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

API = "http://127.0.0.1:8000"

QUESTIONS = [
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
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def _count_dogrula(text: str) -> int:
    return len(re.findall(r"\[DO[ĞG]RULA:", text, flags=re.IGNORECASE))


def _kw_coverage(answer: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    al = answer.lower()
    return sum(1 for kw in keywords if kw.lower() in al) / len(keywords)


def main() -> int:
    # Health check
    try:
        h = httpx.get(f"{API}/health", timeout=5).json()
    except Exception as exc:
        print(f"[XX] FastAPI ulaşılamadı: {exc}", flush=True)
        return 2
    print(f"[OK] FastAPI: {h}", flush=True)

    out_dir = Path("data/e2e_runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"e2e_http_{ts}.jsonl"

    print("=" * 72, flush=True)
    print(f" E2E via HTTP — {len(QUESTIONS)} soru → {out_path}", flush=True)
    print("=" * 72, flush=True)

    rows = []
    n_ok = n_dom_ok = 0
    total_lat = total_cjk = total_dog = 0
    total_kw = 0.0
    pass_v = reject_v = 0

    for qid, q, exp_dom, exp_kw in QUESTIONS:
        print(f"\n[{qid}] {q}", flush=True)
        t0 = time.time()
        try:
            r = httpx.post(
                f"{API}/ask",
                json={"question": q, "want_dilekce": False, "stream": False},
                timeout=600,
            )
            r.raise_for_status()
            data = r.json()
            ok = True
        except Exception as exc:
            data = {"error": str(exc)}
            ok = False

        dt = int((time.time() - t0) * 1000)

        if not ok:
            print(f"  ✗ HTTP ERROR ({dt}ms): {data['error']}", flush=True)
            rows.append({"id": qid, "question": q, "error": data["error"],
                         "elapsed_ms": dt})
            continue

        n_ok += 1
        ans = data.get("answer", "")
        actual_dom = data.get("domain", "unknown")
        verdict = data.get("verdict", "?")
        citations = data.get("citations", [])
        claims = data.get("claims", [])
        n_cjk = _count_cjk(ans)
        n_dog = _count_dogrula(ans)
        kw = _kw_coverage(ans, exp_kw)

        n_dom_ok += int(actual_dom == exp_dom)
        pass_v += int(verdict == "pass")
        reject_v += int(verdict == "reject")
        total_lat += dt
        total_cjk += n_cjk
        total_dog += n_dog
        total_kw += kw

        n_law = sum(1 for c in citations if c.get("doc_type") == "law")
        n_case = sum(1 for c in citations if c.get("doc_type") == "case")
        top_score = max((c.get("score", 0) for c in citations), default=0.0)

        print(f"  → {dt:>5}ms | dom={actual_dom:<10s} verdict={verdict:<7s} "
              f"law={n_law} case={n_case} top={top_score:.2f}", flush=True)
        print(f"    kw_cov={kw:.0%} CJK={n_cjk} DOĞRULA={n_dog} claims={len(claims)}",
              flush=True)
        snippet = ans[:200].replace("\n", " ").strip()
        print(f"    {snippet}...", flush=True)

        rows.append({
            "id": qid, "question": q,
            "expected_domain": exp_dom, "actual_domain": actual_dom,
            "domain_correct": actual_dom == exp_dom,
            "verdict": verdict, "confidence": data.get("confidence"),
            "elapsed_ms": dt, "n_citations": len(citations),
            "n_law": n_law, "n_case": n_case, "top_score": top_score,
            "answer": ans, "keyword_coverage": kw,
            "n_cjk": n_cjk, "n_dogrula": n_dog,
            "claim_count": len(claims),
            "verified_claim_count": sum(1 for c in claims if c.get("verified")),
            "citation_titles": [c.get("title") for c in citations[:8]],
        })

    # JSONL kaydet
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    n = max(1, n_ok)
    print("\n" + "=" * 72, flush=True)
    print(" ÖZET", flush=True)
    print("=" * 72, flush=True)
    print(f"Başarılı koşum     : {n_ok}/{len(QUESTIONS)}", flush=True)
    print(f"Domain doğru       : {n_dom_ok}/{n} ({100*n_dom_ok/n:.0f}%)", flush=True)
    print(f"Verdict pass       : {pass_v}/{n}", flush=True)
    print(f"Verdict reject     : {reject_v}/{n}", flush=True)
    print(f"Ortalama latans    : {total_lat / n:.0f} ms", flush=True)
    print(f"Ort. keyword cov.  : {100*total_kw/n:.0f}%", flush=True)
    print(f"Toplam CJK leak    : {total_cjk} char (Qwen Q4 artifact)", flush=True)
    print(f"[DOĞRULA] toplam   : {total_dog} (hallucination guard hit)", flush=True)
    print(f"\nJSONL: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
