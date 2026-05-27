"""MCP client precondition guard testleri.

`async with` dışında (init edilmeden) kullanım açık RuntimeError vermeli.
Eskiden `assert` kullanılıyordu → `python -O` (PYTHONOPTIMIZE) ile strip edilir,
guard sessizce kaybolur ve None client'a erişim yanıltıcı AttributeError verirdi.
"""

from __future__ import annotations

import pytest

from retrieval.mevzuat_client import MevzuatClient
from retrieval.yargi_client import YargiClient


@pytest.mark.asyncio
async def test_yargi_call_tool_without_context_raises_runtime_error():
    client = YargiClient()  # 'async with' YOK → _client None
    with pytest.raises(RuntimeError):
        await client._call_tool("search_yargitay", {})


@pytest.mark.asyncio
async def test_mevzuat_call_tool_without_context_raises_runtime_error():
    client = MevzuatClient()  # 'async with' YOK → _client None
    with pytest.raises(RuntimeError):
        await client._call_tool("search_mevzuat", {})
