"""mevzuat-mcp tools/list — tool isimleri ve şema keşfi.

https://mevzuat.surucu.dev/mcp public endpoint kullanır.
yargi-mcp ile aynı MCP JSON-RPC protokolü.
"""

from __future__ import annotations

import asyncio
import json

import httpx

MEVZUAT_MCP_URL = "https://mevzuat.surucu.dev/mcp"
PROTOCOL_VERSION = "2024-11-05"
SESSION_HEADER = "mcp-session-id"


def _parse_response(text: str) -> dict:
    """JSON veya SSE chunked."""
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.split("\n"):
        if line.startswith("data: "):
            payload = line[len("data: "):]
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Parse edilemedi: {text[:200]}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        # 1. Initialize
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "adalet-agent-discover", "version": "0.1"},
            },
        }
        resp = await client.post(
            MEVZUAT_MCP_URL,
            json=init_payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
        session_id = resp.headers.get(SESSION_HEADER)
        print(f"Session ID: {session_id}")
        print(f"Init status: {resp.status_code}")
        if session_id is None:
            print("HATA: session_id alınamadı")
            print(f"Headers: {dict(resp.headers)}")
            print(f"Body: {resp.text[:500]}")
            return

        # 2. notifications/initialized
        await client.post(
            MEVZUAT_MCP_URL,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={
                SESSION_HEADER: session_id,
                "Accept": "application/json, text/event-stream",
            },
        )

        # 3. tools/list
        resp = await client.post(
            MEVZUAT_MCP_URL,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={
                SESSION_HEADER: session_id,
                "Accept": "application/json, text/event-stream",
            },
        )
        data = _parse_response(resp.text)
        tools = data.get("result", {}).get("tools", [])

        print(f"\nTotal tools: {len(tools)}")
        print()
        for t in tools[:30]:  # İlk 30 tool
            name = t.get("name", "")
            desc = (t.get("description") or "").strip().split("\n")[0][:120]
            schema = t.get("inputSchema") or {}
            props = list(schema.get("properties", {}).keys())
            print(f"=== {name} ===")
            print(f"  {desc}")
            print(f"  params: {props}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
