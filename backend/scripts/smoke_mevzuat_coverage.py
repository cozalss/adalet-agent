"""Mevzuat coverage smoke — Sprint-5 W12.5.

Her domain için temsili sorgular atılır; sonuçlardaki kanun_kodu dağılımı
DOMAIN_TO_KANUN_KODU'nun beklediği kanunlarla karşılaştırılır.

Kullanım:
    uv run python -m scripts.smoke_mevzuat_coverage

Çıktı:
    Domain bazında "beklenen kanun / dönen kanun" eşleşmesi + summary.

Beklenen sonuç (W12 hedefi):
    8 domain × 3 sorgu = 24 koşma.
    Her sorgu için top-K mevzuat hit'lerinin >= 1 tanesi expected_kanun
    listesinde olmalı. Tüm domain'ler için kanun@1 >= 0.85.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from agents.config import DOMAIN_TO_KANUN_KODU
from retrieval.hybrid_search import search
from retrieval.vector_store import get_client

logger = logging.getLogger("smoke.mevzuat_coverage")

# Domain bazlı temsili sorgular (her domain için 3 farklı angle).
# Bu sorgular gerçek vatandaş sorularını simüle eder.
DOMAIN_QUERIES: dict[str, tuple[str, ...]] = {
    "tuketici": (
        "ayıplı buzdolabı iade hakkım var mı",
        "kapıdan satışta cayma hakkı süresi",
        "banka kredi kartı sözleşmesi haksız şart",
    ),
    "isHukuku": (
        "5 yıllık çalışmadan sonra istifa kıdem hakkı",
        "fazla mesai ücreti hesaplama yöntemi",
        "iş kazasında işveren sorumluluğu",
    ),
    "kira": (
        "kira artış oranı sınırı 2025",
        "kiracı tahliyesi için ihtar süresi",
        "ihtiyaç nedeniyle tahliye davası",
    ),
    "icra": (
        "icra takibine itiraz nasıl yapılır",
        "maaş haczi sınırı",
        "kambiyo senedi takibi süreci",
    ),
    "trafik": (
        "trafik kazasında manevi tazminat",
        "ZMSS poliçesi limit aşılırsa",
        "araç değer kaybı tazminatı",
    ),
    "vergi": (
        "vergi ziyaı cezası ne zaman düşer",
        "KDV iadesi başvuru süresi",
        "ÖTV hesaplama hatası düzeltme",
    ),
    "tapu": (
        "tapu iptali ve tescil davası",
        "izale-i şuyu satış usulü",
        "kamulaştırma bedel tespiti",
    ),
    "idari": (
        "memur disiplin cezası iptal",
        "kamu ihalesinden yasaklanma süresi",
        "iptal davası açma süresi",
    ),
}


async def _probe_one(query: str, domain: str, expected_kanunlar: tuple[str, ...]) -> bool:
    """Tek bir sorguyu çalıştır, top-K'da expected kanun var mı kontrol et."""
    hits = await search(query, top_k=10)
    hit_kanunlar = {
        h.metadata.get("kanun_kodu")
        for h in hits
        if h.metadata.get("doc_type") == "law" and h.metadata.get("kanun_kodu")
    }
    expected_set = set(expected_kanunlar)
    overlap = hit_kanunlar & expected_set
    ok = bool(overlap)
    status = "OK" if ok else "MISS"
    logger.info(
        "[%s] %-12s | hit: %s | expected: %s | %s",
        status,
        domain,
        sorted(hit_kanunlar) or "-",
        sorted(expected_set),
        query,
    )
    return ok


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-4s | %(message)s",
    )
    logger.info("mevzuat_coverage_smoke_started")

    qdrant = get_client()
    try:
        total = 0
        ok = 0
        for domain, queries in DOMAIN_QUERIES.items():
            expected = DOMAIN_TO_KANUN_KODU.get(domain, ())
            if not expected:
                logger.warning("domain_no_expected_kanun %s", domain)
                continue
            for q in queries:
                total += 1
                if await _probe_one(q, domain, expected):
                    ok += 1

        ratio = (ok / total) if total else 0.0
        logger.info("=" * 60)
        logger.info("Sonuç: %d / %d sorgu OK (%.0f%%)", ok, total, ratio * 100)
        # Hedef: kanun@1 >= 0.85
        return 0 if ratio >= 0.85 else 1
    finally:
        await qdrant.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
