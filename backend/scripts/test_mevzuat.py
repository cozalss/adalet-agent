"""Mevzuat-mcp çağrılarını test et — gerçek response field isimleri."""

from __future__ import annotations

import asyncio

from retrieval.mevzuat_client import MevzuatClient


async def main() -> None:
    async with MevzuatClient() as client:
        # 1. TKHK ara
        print("=== search_mevzuat(mevzuat_no=6502) ===")
        raw = await client._call_tool(
            "search_mevzuat",
            {"mevzuat_no": "6502", "mevzuat_tur": "KANUN", "page_size": 5},
        )
        print(raw.get("raw_text", "")[:300])
        print()

        # 2. get_mevzuat_content(103101)
        print("=== get_mevzuat_content(103101) ===")
        c = await client._call_tool(
            "get_mevzuat_content",
            {"mevzuat_id": "103101"},
        )
        print("Top-level keys:", list(c.keys()))
        text = c.get("raw_text") or c.get("markdown_content") or c.get("content") or ""
        print(f"Length: {len(text)}")
        print(text[:1500])
        print()


if __name__ == "__main__":
    asyncio.run(main())
