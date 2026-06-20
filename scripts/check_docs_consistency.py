"""Check high-signal documentation consistency rules.

This script intentionally checks the current/public entry documents, not every
historical snapshot. Historical documents may keep old metrics when they carry a
snapshot banner and link back to docs/CURRENT_STATUS.md.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CURRENT_DOCS = [
    Path("README.md"),
    Path("docs/README.md"),
    Path("docs/CURRENT_STATUS.md"),
    Path("docs/DOCUMENTATION_GOVERNANCE.md"),
    Path("docs/architecture.md"),
    Path("docs/yarisma-ozeti.md"),
    Path("frontend/.env.example"),
]

HISTORICAL_DOCS = [
    Path("docs/PROJE-DURUMU.md"),
    Path("docs/DEGISIKLIK-GUNLUGU.md"),
    Path("docs/ablation_study.md"),
    Path("docs/theses/measured-results.md"),
    Path("docs/audit/2026-06-09-worldclass-audit.md"),
]

REQUIRED_SNIPPETS = {
    Path("docs/CURRENT_STATUS.md"): [
        "tek doğru kaynak",
        "2026-06-21",
        "1532 passed",
        "254 tests",
        "11 passed",
        "Qwen3.5-9B-UD-Q4_K_XL.gguf",
        "misafir/localStorage-only sohbet modu yoktur",
    ],
    Path("README.md"): [
        "docs/CURRENT_STATUS.md",
        "unverified",
        "Qwen3.5-9B-UD-Q4_K_XL",
        "1532 backend hızlı test + 254 frontend test + 11 e2e",
    ],
    Path("docs/README.md"): [
        "CURRENT_STATUS.md",
        "DOCUMENTATION_GOVERNANCE.md",
        "Tarihsel belgelerdeki eski model adları",
    ],
    Path("docs/DOCUMENTATION_GOVERNANCE.md"): [
        "Metrik Yazma Kuralı",
        "Snapshot Banner Kuralı",
        "scripts/check_docs_consistency.py",
    ],
}

FORBIDDEN_IN_CURRENT = [
    re.compile(r"1240\+"),
    re.compile(r"~200\s+frontend", re.IGNORECASE),
    re.compile(r"1313\s+test", re.IGNORECASE),
    re.compile(r"771\+\s+backend", re.IGNORECASE),
    re.compile(r'"misafir"\s+ak[ıi]ş[ıi]', re.IGNORECASE),
    re.compile(r"doğrulanamayan(?:ı| iddiaların)?\s+redd", re.IGNORECASE),
    re.compile(r"kaynağı doğrulanmamış hiçbir hukuki iddia", re.IGNORECASE),
]


def read(path: Path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> int:
    errors: list[str] = []

    for path in CURRENT_DOCS + HISTORICAL_DOCS:
        if not (ROOT / path).exists():
            errors.append(f"missing: {path}")

    for path, snippets in REQUIRED_SNIPPETS.items():
        text = read(path)
        for snippet in snippets:
            if snippet not in text:
                errors.append(f"{path}: missing required snippet: {snippet!r}")

    for path in CURRENT_DOCS:
        text = read(path)
        for pattern in FORBIDDEN_IN_CURRENT:
            match = pattern.search(text)
            if match:
                errors.append(f"{path}: forbidden current-doc phrase: {match.group(0)!r}")

    for path in HISTORICAL_DOCS:
        text = read(path)
        has_banner = "[!IMPORTANT]" in text or "[!NOTE]" in text
        links_current = "CURRENT_STATUS.md" in text
        if not has_banner or not links_current:
            errors.append(f"{path}: historical doc needs snapshot banner and CURRENT_STATUS link")

    if errors:
        print("Documentation consistency check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Documentation consistency check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
