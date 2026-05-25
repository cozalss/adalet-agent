"""yargi-mcp tools/list — full schema discovery.

Coverage genişletme için: tarih aralığı, daire/birim, kanun no gibi
keşfedilmemiş parametreleri bul. Çıktıyı docs/yargi-mcp-schema.json'a yazar.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from retrieval.yargi_client import YargiClient


async def main() -> None:
    out_path = Path(__file__).parent.parent.parent / "docs" / "yargi-mcp-schema.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    async with YargiClient() as client:
        # tools/list JSON-RPC çağrısı
        client._rpc_id += 1
        assert client._client is not None
        payload = {
            "jsonrpc": "2.0",
            "id": client._rpc_id,
            "method": "tools/list",
            "params": {},
        }
        resp = await client._client.post(
            "",
            json=payload,
            headers={"mcp-session-id": client._session_id or ""},
        )
        from retrieval.yargi_client import _parse_mcp_response
        data = _parse_mcp_response(resp.text)
        tools = data.get("result", {}).get("tools", [])

        # Bedesten + Anayasa tool'larını filtrele (en alakalı olanlar)
        relevant = [
            t for t in tools
            if any(k in t.get("name", "").lower() for k in ("bedesten", "anayasa", "yargitay", "danistay"))
        ]

        print(f"Total tools: {len(tools)}")
        print(f"Relevant (bedesten/anayasa/yargitay/danistay): {len(relevant)}")
        print()
        for t in relevant:
            print(f"=== {t['name']} ===")
            print(t.get("description", "")[:200])
            schema = t.get("inputSchema") or t.get("input_schema") or {}
            props = schema.get("properties", {})
            print("Properties:")
            for prop_name, prop_def in props.items():
                desc = prop_def.get("description", "")
                tipi = prop_def.get("type") or prop_def.get("anyOf", [{}])[0].get("type", "?")
                print(f"  {prop_name} ({tipi}): {desc[:120]}")
            print()

        out_path.write_text(json.dumps(tools, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Full schema written: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
