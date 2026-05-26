"""Per-domain karar sayım raporu — Sprint-5 W13.7.

`data/seed_state/*.jsonl` dosyalarını okuyup her (court, domain) için kaç karar
seeded olduğunu raporlar. Sprint-5 hedeflerine göre eksiklik tablosu çıkarır.

Kullanım:
    uv run python -m eval.domain_audit
    uv run python -m eval.domain_audit --final   # Sprint-5 sonu raporu

Çıktı:
    - Konsola tablo
    - eval/runs/Sprint5_domain_audit_<timestamp>.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("eval.domain_audit")

# Sprint-5 hedef tablosu (plan W11 audit ile uyumlu).
SPRINT5_TARGETS: dict[str, int] = {
    "tuketici": 1500,
    "isHukuku": 2000,
    "kira": 1200,
    "icra": 800,
    "trafik": 800,
    "vergi": 800,
    "tapu": 700,
    "idari": 1000,
}

COURTS: tuple[str, ...] = ("yargitay", "danistay", "anayasa")
DOMAINS: tuple[str, ...] = (
    "tuketici",
    "isHukuku",
    "kira",
    "icra",
    "trafik",
    "vergi",
    "tapu",
    "idari",
)

SEED_STATE_DIR = Path("data/seed_state")
REPORT_DIR = Path("eval/runs")


def _count_jsonl(path: Path) -> int:
    """JSONL dosyasındaki status=ok kayıtların sayısı."""
    if not path.exists():
        return 0
    n = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # mark_done status=ok kayıtlar sayılır
                if rec.get("status") == "ok":
                    n += 1
    except OSError as exc:
        logger.warning("read_failed %s: %s", path, exc)
    return n


def _gather() -> dict[str, dict[str, int]]:
    """Her domain için court başına seed sayısını topla."""
    out: dict[str, dict[str, int]] = {}
    for domain in DOMAINS:
        domain_counts: dict[str, int] = {}
        total = 0
        for court in COURTS:
            path = SEED_STATE_DIR / f"{court}_{domain}.jsonl"
            n = _count_jsonl(path)
            domain_counts[court] = n
            total += n
        domain_counts["total"] = total
        out[domain] = domain_counts
    return out


def _format_table(counts: dict[str, dict[str, int]]) -> str:
    """Markdown tablo üret."""
    lines: list[str] = []
    lines.append("| Domain | Yargıtay | Danıştay | AYM | Toplam | Hedef | Gap | % |")
    lines.append("|---|---|---|---|---|---|---|---|")
    total_actual = 0
    total_target = 0
    for domain in DOMAINS:
        c = counts.get(domain, {})
        ya = c.get("yargitay", 0)
        da = c.get("danistay", 0)
        am = c.get("anayasa", 0)
        tot = c.get("total", 0)
        tgt = SPRINT5_TARGETS.get(domain, 0)
        gap = max(0, tgt - tot)
        pct = (100 * tot / tgt) if tgt else 0.0
        lines.append(
            f"| {domain} | {ya} | {da} | {am} | **{tot}** | {tgt} | {gap} | {pct:.0f}% |"
        )
        total_actual += tot
        total_target += tgt
    pct_total = (100 * total_actual / total_target) if total_target else 0.0
    lines.append(
        f"| **TOPLAM** | — | — | — | **{total_actual}** | "
        f"**{total_target}** | **{total_target - total_actual}** | **{pct_total:.0f}%** |"
    )
    return "\n".join(lines)


def _write_report(counts: dict[str, dict[str, int]], final: bool) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = "final" if final else timestamp
    path = REPORT_DIR / f"Sprint5_domain_audit_{suffix}.md"

    title = "Sprint-5 Final Domain Audit" if final else f"Sprint-5 Domain Audit ({timestamp})"
    body = [
        f"# {title}",
        "",
        f"> Tarih: {datetime.now(UTC).isoformat()}",
        f"> Kaynak: `{SEED_STATE_DIR}/*.jsonl`",
        "",
        "## Per-Domain Karar Dağılımı (status=ok)",
        "",
        _format_table(counts),
        "",
        "## Notlar",
        "",
        "- Hedefler `eval/domain_audit.SPRINT5_TARGETS` içinde tanımlı.",
        "- `Gap` = hedef - şu an. Sprint-5 sonunda 0 olmalı (veya küçük tolerans).",
        "- `%` = (şu an / hedef) × 100. Domain bazlı progress göstergesi.",
    ]
    path.write_text("\n".join(body), encoding="utf-8")
    return path


async def _qdrant_counts() -> dict[str, dict[str, int]]:
    """Qdrant'tan canlı sayım — JSONL'dan bağımsız.

    Her domain için:
    - laws         : kanun chunk sayısı (kanun_kodu var, domain == bu domain'e mapping)
    - cases        : karar chunk sayısı (court ∈ {yargitay, danistay, anayasa, ...}, domain match)
    - regulator    : KVKK / Rekabet / Sayıştay / GİB chunk sayısı (regulator var, domain match)
    - total        : tüm chunks bu domain için
    """
    from qdrant_client import models

    from retrieval.vector_store import COLLECTION_NAME, get_client

    client = get_client()
    out: dict[str, dict[str, int]] = {}
    try:
        for domain in DOMAINS:
            d = {}
            # All chunks in this domain
            f = models.Filter(must=[
                models.FieldCondition(key="domain", match=models.MatchValue(value=domain))
            ])
            d["total"] = (await client.count(COLLECTION_NAME, count_filter=f)).count

            # Cases — chunks with court ∈ {yargitay, danistay, anayasa}
            f_yargi = models.Filter(must=[
                models.FieldCondition(key="domain", match=models.MatchValue(value=domain)),
                models.FieldCondition(key="court", match=models.MatchAny(any=[
                    "yargitay", "danistay", "anayasa", "anayasa_bireysel_basvuru",
                    "ANAYASA_BIREYSEL_BASVURU", "YARGITAYKARARI", "DANISTAYKARAR"
                ])),
            ])
            d["cases"] = (await client.count(COLLECTION_NAME, count_filter=f_yargi)).count

            # Regulator chunks
            f_reg = models.Filter(must=[
                models.FieldCondition(key="domain", match=models.MatchValue(value=domain)),
                models.FieldCondition(key="regulator", match=models.MatchAny(any=[
                    "kvkk", "rekabet", "sayistay", "gib_ozelge",
                    "bddk", "spk", "sigorta_tahkim"
                ])),
            ])
            d["regulator"] = (await client.count(COLLECTION_NAME, count_filter=f_reg)).count

            out[domain] = d

        # Laws (no domain field, kanun_kodu set)
        f_laws = models.Filter(must=[
            models.FieldCondition(key="kanun_kodu", match=models.MatchAny(any=[
                "TKHK", "TBK", "BK", "TTK", "TMK", "KVKK", "IK", "SGK", "DMK",
                "VUK", "GV", "KurumlarV", "KDV", "OTV", "DV", "MTV", "EMLAKV",
                "IIK", "AATUHK", "KTK", "ZMSS", "TPK", "KMK", "BELEDIYE",
                "BUYUKSEHIR", "IYUK", "DUHK", "KIHK", "TKK", "AVHK", "SIGORTA",
                "BANK", "RKHK", "OHK",
            ])),
        ])
        law_total = (await client.count(COLLECTION_NAME, count_filter=f_laws)).count
        out["__laws__"] = {"laws_total": law_total}

        # Overall total
        out["__overall__"] = {"total": (await client.count(COLLECTION_NAME)).count}
    finally:
        await client.close()
    return out


def _format_qdrant_table(counts: dict[str, dict[str, int]]) -> str:
    lines: list[str] = []
    lines.append("| Domain | Cases | Regulator | Total | Hedef | % |")
    lines.append("|---|---|---|---|---|---|")
    total_actual = 0
    total_target = 0
    for domain in DOMAINS:
        c = counts.get(domain, {})
        cases = c.get("cases", 0)
        reg = c.get("regulator", 0)
        tot = c.get("total", 0)
        tgt = SPRINT5_TARGETS.get(domain, 0)
        pct = (100 * tot / tgt) if tgt else 0.0
        lines.append(f"| {domain} | {cases} | {reg} | **{tot}** | {tgt} | {pct:.0f}% |")
        total_actual += tot
        total_target += tgt
    pct_total = (100 * total_actual / total_target) if total_target else 0.0
    lines.append(
        f"| **DOMAIN TOPLAM** | — | — | **{total_actual}** | "
        f"**{total_target}** | **{pct_total:.0f}%** |"
    )
    laws_total = counts.get("__laws__", {}).get("laws_total", 0)
    overall = counts.get("__overall__", {}).get("total", 0)
    lines.append("")
    lines.append(f"**Kanun (mevzuat) chunks**: {laws_total}")
    lines.append(f"**Qdrant overall total chunks**: {overall}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-domain seed audit")
    parser.add_argument("--final", action="store_true", help="Sprint-5 final raporu")
    parser.add_argument("--qdrant", action="store_true", help="Qdrant'tan canlı sayım da yap")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-4s | %(message)s",
    )
    logger.info("domain_audit_started")

    counts = _gather()
    table = _format_table(counts)
    print()
    print(table)
    print()

    qdrant_table: str | None = None
    qdrant_counts: dict[str, dict[str, int]] | None = None
    if args.qdrant or args.final:
        qdrant_counts = asyncio.run(_qdrant_counts())
        qdrant_table = _format_qdrant_table(qdrant_counts)
        print("\n=== Qdrant Live Counts ===\n")
        print(qdrant_table)
        print()

    report_path = _write_report(counts, final=args.final)
    if qdrant_table:
        # Qdrant tablosunu raporun sonuna ekle
        existing = report_path.read_text(encoding="utf-8")
        existing += f"\n\n## Qdrant Live Counts\n\n{qdrant_table}\n"
        report_path.write_text(existing, encoding="utf-8")
    logger.info("report_written %s", report_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
