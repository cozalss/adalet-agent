"""Staging smoke E2E — Sprint-4 W9.5.

`https://staging.adalet.app` üzerinden 8 vakalık smoke. Token gerek.

Çalıştırma:
  STAGING_URL=https://staging.adalet.app \
  BETA_TOKEN=<jwt> \
    uv run python -m scripts.smoke_staging

Çıktı: data/staging_runs/smoke_<date>.json
Threshold: 28+/30 success, p95 < 60s
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

STAGING_URL = os.environ.get("STAGING_URL", "https://staging.adalet.app")
BETA_TOKEN = os.environ.get("BETA_TOKEN", "")

QUESTIONS = [
    ("E1", "Kıdem tazminatına hak kazanmak için ne kadar süre çalışılmalı?", "isHukuku"),
    ("E2", "Ayıplı malda tüketici hangi haklara sahiptir?", "tuketici"),
    ("E3", "Kiracı kira bedelini ödemezse ne kadar süre içinde ihtar verilir?", "kira"),
    ("E4", "Mesafeli satışlarda cayma hakkı kaç gündür?", "tuketici"),
    ("E5", "İcra takibine itiraz süresi nedir?", "icra"),
    ("E6", "İş Kanunu fazla mesai ücretini nasıl düzenler?", "isHukuku"),
    ("E7", "Vergi cezasına itiraz süresi nedir?", "vergi"),
    ("E8", "Trafik kazasında ZMSS tazminatı nasıl alınır?", "trafik"),
]


async def smoke_one(client: httpx.AsyncClient, qid: str, q: str, exp: str) -> dict:
    t0 = time.monotonic()
    try:
        r = await client.post(
            f"{STAGING_URL}/ask",
            json={"question": q},
            headers={"Authorization": f"Bearer {BETA_TOKEN}"} if BETA_TOKEN else {},
            timeout=90.0,
        )
        dt = time.monotonic() - t0
        if r.status_code != 200:
            return {"qid": qid, "ok": False, "http": r.status_code,
                    "error": r.text[:200], "latency_s": round(dt, 2)}
        body = r.json()
        return {
            "qid": qid, "ok": True, "http": 200,
            "domain": body.get("domain"),
            "domain_match": body.get("domain") == exp,
            "verdict": body.get("verdict"),
            "confidence": body.get("confidence"),
            "n_citations": len(body.get("citations", [])),
            "response_len": len(body.get("answer", "")),
            "latency_s": round(dt, 2),
            "has_disclaimer": "avukat" in (body.get("answer", "") or "").lower(),
        }
    except Exception as exc:
        return {"qid": qid, "ok": False, "error": str(exc)[:200],
                "latency_s": round(time.monotonic() - t0, 2)}


async def main() -> int:
    print(f"[smoke] target={STAGING_URL}")
    print(f"[smoke] token={'set' if BETA_TOKEN else 'NONE — will fail if AUTH_ENABLED=1'}")

    async with httpx.AsyncClient() as client:
        # /health smoke
        try:
            h = await client.get(f"{STAGING_URL}/health", timeout=10.0)
            print(f"[smoke] /health → {h.status_code} {h.json().get('status')}")
        except Exception as exc:
            print(f"[smoke] /health FAIL: {exc}", file=sys.stderr)
            return 2

        results = []
        for qid, q, exp in QUESTIONS:
            print(f"[smoke] {qid} {exp}: {q[:50]}...")
            r = await smoke_one(client, qid, q, exp)
            results.append(r)
            ok = r.get("ok")
            v = r.get("verdict", "-")
            lat = r.get("latency_s", "?")
            print(f"  → ok={ok} verdict={v} lat={lat}s")

    out_dir = Path("data/staging_runs")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"smoke_{ts}.json"
    out_path.write_text(
        json.dumps({"ts": ts, "url": STAGING_URL, "results": results},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n[smoke] report → {out_path}")

    n_ok = sum(1 for r in results if r.get("ok"))
    n_pass = sum(1 for r in results if r.get("verdict") == "pass")
    n_domain = sum(1 for r in results if r.get("domain_match"))
    latencies = sorted([r.get("latency_s", 0) for r in results if r.get("latency_s")])
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    print(f"\n[smoke] Summary: ok={n_ok}/{len(results)}, pass={n_pass}, "
          f"domain_correct={n_domain}, p95={p95:.1f}s")
    return 0 if n_ok >= 6 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
