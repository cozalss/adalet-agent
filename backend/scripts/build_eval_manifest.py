"""Eval runs manifest — Sprint-4 W10.3.

`eval/runs/` altındaki tüm JSON çıktıları index'le:
  - timestamp, sha (varsa), benchmark version, modes, metrics summary

Çıktı: eval/runs/manifest.json

Çalıştırma:
  uv run python -m scripts.build_eval_manifest
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

RUNS_DIR = Path("eval/runs")


def _git_sha(path: Path) -> str | None:
    """Dosyanın commit edildiği sha (varsa)."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%h", "--", str(path)],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _summarize(data: dict) -> dict:
    """JSON run output'tan kısa özet üret."""
    summary: dict[str, object] = {}
    # freeze_baseline çıktı formatı: {"benchmark_version": "v2", "modes": {...}}
    if "modes" in data and isinstance(data["modes"], dict):
        modes_data = data["modes"]
        summary["modes"] = list(modes_data.keys())
        if modes_data:
            # En iyi mode'un D@1 ve kanun@5'i
            best_d1 = max(
                (m.get("d_at_1", 0) for m in modes_data.values() if isinstance(m, dict)),
                default=0,
            )
            best_k5 = max(
                (m.get("kanun_at_5", 0) for m in modes_data.values() if isinstance(m, dict)),
                default=0,
            )
            summary["best_d_at_1"] = round(best_d1, 3)
            summary["best_kanun_at_5"] = round(best_k5, 3)

    if "benchmark_version" in data:
        summary["benchmark_version"] = data["benchmark_version"]
    if "n_cases" in data:
        summary["n_cases"] = data["n_cases"]
    if "results" in data and isinstance(data["results"], list):
        summary["n_results"] = len(data["results"])

    # Ragas / judge
    if "faithfulness" in data:
        summary["faithfulness"] = round(float(data["faithfulness"]), 3)
    if "answer_relevancy" in data:
        summary["answer_relevancy"] = round(float(data["answer_relevancy"]), 3)
    if "context_precision" in data:
        summary["context_precision"] = round(float(data["context_precision"]), 3)
    if "average_score" in data:
        summary["judge_avg"] = round(float(data["average_score"]), 3)

    # Cost report
    if "total_tokens" in data and "estimated_cost_usd" in data:
        summary["total_tokens"] = data["total_tokens"]
        summary["estimated_cost_usd"] = data["estimated_cost_usd"]

    return summary


def main() -> int:
    if not RUNS_DIR.exists():
        print(f"[manifest] {RUNS_DIR} yok", file=sys.stderr)
        return 1

    entries: list[dict] = []
    for p in sorted(RUNS_DIR.glob("*.json")):
        if p.name == "manifest.json":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[manifest] {p.name}: skip ({exc})", file=sys.stderr)
            continue

        # Filename'den ts/sha pattern: v1_hyde_<sha>.json, v2_w2_<sha>.json
        sha_match = re.search(r"_([a-f0-9]{6,12})\.json$", p.name)
        version_match = re.match(r"^(v\d+(?:_[a-z]+)*)", p.name)

        entry: dict = {
            "file": p.name,
            "size_bytes": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat(),
            "version": version_match.group(1) if version_match else None,
            "embedded_sha": sha_match.group(1) if sha_match else None,
            "git_sha": _git_sha(p),
            "summary": _summarize(data),
        }
        entries.append(entry)

    # W*_changes.md changelog'ları da index'le
    changelogs = []
    for p in sorted(RUNS_DIR.glob("W*_changes.md")):
        changelogs.append({
            "file": p.name,
            "week": re.match(r"W(\d+)", p.name).group(1) if re.match(r"W(\d+)", p.name) else None,
            "size_bytes": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat(),
        })

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "n_runs": len(entries),
        "n_changelogs": len(changelogs),
        "runs": entries,
        "changelogs": changelogs,
    }

    out_path = RUNS_DIR / "manifest.json"
    out_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[manifest] {len(entries)} runs + {len(changelogs)} changelogs -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
