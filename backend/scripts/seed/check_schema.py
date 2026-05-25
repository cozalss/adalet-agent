"""search_anayasa_unified ve get_anayasa_document_markdown şemasını canlı API'den çıkar.

Kullanım:
    uv run python -m scripts.seed.check_schema
"""

from __future__ import annotations

import asyncio

import httpx

from retrieval.yargi_client import SESSION_HEADER, YARGI_MCP_URL, _parse_mcp_response

TARGET_TOOLS = {
    "search_anayasa_unified",
    "get_anayasa_document_unified",
    "get_anayasa_document_markdown",
    "search_bedesten_unified",
    "get_bedesten_document_markdown",
}


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
                    "clientInfo": {"name": "schema-check", "version": "0.1"},
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
        tools = _parse_mcp_response(tools_resp.text)["result"]["tools"]

    for tool in tools:
        if tool["name"] not in TARGET_TOOLS:
            continue
        print(f"\n{'=' * 70}")
        print(f"TOOL: {tool['name']}")
        print(f"{'=' * 70}")
        print(f"\nDESCRIPTION:\n{tool.get('description', '')[:500]}\n")
        schema = tool.get("inputSchema", {})
        required = schema.get("required", [])
        print("PARAMETERS:")
        for name, defn in schema.get("properties", {}).items():
            marker = "*" if name in required else " "
            kind = defn.get("type") or defn.get("anyOf") or "?"
            desc = (defn.get("description") or "").replace("\n", " ")[:120]
            print(f"  {marker} {name}: {kind!r}")
            if "enum" in defn:
                print(f"      enum: {defn['enum']}")
            if desc:
                print(f"      {desc}")


if __name__ == "__main__":
    asyncio.run(main())
