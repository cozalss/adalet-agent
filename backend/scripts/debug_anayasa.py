"""Anayasa get_document response field'larını debug."""

from __future__ import annotations

import asyncio
import json

from retrieval.yargi_client import YargiClient


async def main() -> None:
    async with YargiClient() as client:
        # 1) Önce bir karar bul
        search_raw = await client._call_tool(
            "search_anayasa_unified",
            {
                "decision_type": "bireysel_basvuru",
                "keywords": ["mülkiyet"],
                "page_to_fetch": 1,
            },
        )
        first = search_raw["decisions"][0]
        url = first["decision_page_url"]
        ref = first["decision_reference_no"]
        print(f"Test URL: {url}")
        print(f"Reference: {ref}")
        print()

        # 2) Şimdi get_document çağrısını yap
        doc_raw = await client._call_tool(
            "get_anayasa_document_unified",
            {"document_url": url, "page_number": 1},
        )
        print("=== GET_DOCUMENT KEYS ===")
        print(list(doc_raw.keys()))
        print()
        print("=== GET_DOCUMENT (full, first 3000 chars) ===")
        print(json.dumps(doc_raw, ensure_ascii=False, indent=2)[:3000])


if __name__ == "__main__":
    asyncio.run(main())
