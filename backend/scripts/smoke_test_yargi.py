"""yargi-mcp bağlantı dumusı — public instance'a 3 küçük Yargıtay sorgusu atar.

Kullanım:
    uv run python scripts/smoke_test_yargi.py
"""

from __future__ import annotations

import asyncio
import logging
import sys

from retrieval.yargi_client import YargiClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("smoke")


TEST_QUERIES = [
    ("tüketici", "tuketici"),
    ("kıdem tazminatı", "isHukuku"),
    ("kira sözleşmesi", "kira"),
]


async def main() -> int:
    async with YargiClient() as client:
        logger.info("session initialized, sorgu testleri başlıyor")

        total_ok = 0
        for phrase, domain in TEST_QUERIES:
            try:
                decisions = await client.search_yargitay(phrase, page_size=3)
                logger.info(
                    "%-15s | %-10s | %d karar bulundu",
                    domain,
                    phrase,
                    len(decisions),
                )
                for i, decision in enumerate(decisions[:2], start=1):
                    chamber = decision.chamber or "-"
                    date = decision.date or "-"
                    doc_id = decision.document_id or "-"
                    logger.info("   %d. %s | %s | id=%s", i, chamber, date, doc_id)
                if decisions:
                    total_ok += 1
            except Exception as exc:
                logger.error("'%s' sorgusu başarısız: %s", phrase, exc, exc_info=True)

        logger.info("=" * 60)
        logger.info("Sonuç: %d / %d sorgu başarılı", total_ok, len(TEST_QUERIES))
        return 0 if total_ok == len(TEST_QUERIES) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
