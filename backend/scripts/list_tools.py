"""yargi-mcp'nin gerçek tool şemasını listele — özellikle search_bedesten_unified."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

from retrieval.yargi_client import (
    SESSION_HEADER,
    YARGI_MCP_URL,
    _parse_mcp_response,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


async def main() -> None:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
        init_resp = await client.post(
            YARGI_MCP_URL,
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "schema-probe", "version": "0.1"},
                },
                "id": 1,
            },
        )
        session_id = init_resp.headers[SESSION_HEADER]
        await client.post(
            YARGI_MCP_URL,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers={SESSION_HEADER: session_id},
        )

        tools_resp = await client.post(
            YARGI_MCP_URL,
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
            headers={SESSION_HEADER: session_id},
        )
        envelope = _parse_mcp_response(tools_resp.text)

        tools = envelope.get("result", {}).get("tools", [])
        print(f"\nToplam {len(tools)} tool var:\n")

        for tool in tools:
            print(f"  - {tool['name']}")

        target = next(
            (t for t in tools if t["name"] == "search_bedesten_unified"),
            None,
        )
        if target:
            print(f"\n=== search_bedesten_unified ŞEMASI ===")
            print(f"\nAçıklama:\n  {target.get('description', '')[:300]}")
            schema = target.get("inputSchema", {})
            print(f"\nParametreler:")
            for prop_name, prop_def in schema.get("properties", {}).items():
                kind = prop_def.get("type") or prop_def.get("anyOf") or "?"
                desc = (prop_def.get("description") or "")[:80]
                required = prop_name in schema.get("required", [])
                marker = "*" if required else " "
                print(f"  {marker} {prop_name}: {kind!r}")
                if desc:
                    print(f"      {desc}")


if __name__ == "__main__":
    asyncio.run(main())
