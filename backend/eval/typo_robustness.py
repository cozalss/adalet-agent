"""Generate typo-robustness eval cases from existing benchmark JSONL.

This module does not call models. It creates deterministic noisy variants that
can be fed into the existing retrieval/e2e runners to compare clean vs typo
performance.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from pathlib import Path

_TOKEN_RE = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü]+", re.UNICODE)
_TR_ASCII = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "Ç": "C",
        "Ğ": "G",
        "İ": "I",
        "Ö": "O",
        "Ş": "S",
        "Ü": "U",
    }
)
_PROTECTED_RE = re.compile(
    r"^(?:\d|m\.?|madde|tbk|tkhk|ik|iik|vuk|ktk|tmk|ttk|kmk|kvkk)$",
    re.IGNORECASE,
)
_BOUNDARY_PHRASES = (
    "işe iade",
    "kıdem tazminatı",
    "ihbar tazminatı",
    "kira artışı",
    "tüketici hakem",
    "ödeme emri",
    "trafik cezası",
    "vergi cezası",
)


def strip_diacritics(text: str) -> str:
    return text.translate(_TR_ASCII)


def _protected(token: str) -> bool:
    return bool(_PROTECTED_RE.match(token)) or any(ch.isdigit() for ch in token)


def _drop_middle_char(token: str) -> str:
    if len(token) < 5 or _protected(token):
        return token
    idx = max(1, len(token) // 2)
    return token[:idx] + token[idx + 1 :]


def _swap_middle_chars(token: str) -> str:
    if len(token) < 6 or _protected(token):
        return token
    idx = max(1, len(token) // 2 - 1)
    chars = list(token)
    chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
    return "".join(chars)


def _edit_tokens(question: str) -> str:
    edits_left = 2

    def repl(match: re.Match[str]) -> str:
        nonlocal edits_left
        token = match.group(0)
        if edits_left <= 0 or _protected(token) or len(token) < 5:
            return token
        edits_left -= 1
        return _drop_middle_char(token) if edits_left % 2 else _swap_middle_chars(token)

    return _TOKEN_RE.sub(repl, question)


def _join_boundary(question: str) -> str:
    low = question.lower()
    for phrase in _BOUNDARY_PHRASES:
        pos = low.find(phrase)
        if pos >= 0:
            original = question[pos : pos + len(phrase)]
            return question[:pos] + original.replace(" ", "") + question[pos + len(phrase) :]
    return question


def mutate_question(question: str, level: str) -> str:
    """Return a deterministic typo variant for a benchmark question."""
    if level == "diacritic":
        return strip_diacritics(question)
    if level == "single_edit":
        return _edit_tokens(question)
    if level == "boundary":
        joined = _join_boundary(question)
        return joined if joined != question else _edit_tokens(strip_diacritics(question))
    raise ValueError(f"unknown typo level: {level}")


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_typo_cases(
    rows: Iterable[dict],
    *,
    levels: tuple[str, ...] = ("diacritic", "single_edit", "boundary"),
) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        question = str(row.get("soru") or row.get("question") or "")
        if not question:
            continue
        for level in levels:
            mutated = mutate_question(question, level)
            if mutated == question:
                continue
            item = dict(row)
            item["id"] = f"{row.get('id', 'case')}_typo_{level}"
            item["soru"] = mutated
            item["clean_soru"] = question
            item["typo_level"] = level
            item["source"] = f"{row.get('source', 'benchmark')}:typo"
            out.append(item)
    return out


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/eval_benchmark/benchmark_v2.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/eval_benchmark/typo_cases.jsonl"),
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    rows = load_jsonl(args.input)
    if args.limit > 0:
        rows = rows[: args.limit]
    typo_cases = build_typo_cases(rows)
    write_jsonl(args.output, typo_cases)
    print(f"wrote {len(typo_cases)} typo cases to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
