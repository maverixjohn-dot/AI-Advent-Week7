"""Синхронный клиент к MCP-серверу CRM для использования из агента.

fastmcp.Client — асинхронный, агент и Flet-обработчики работают
в синхронном коде, поэтому здесь фоновый event loop в отдельном
потоке. Соединение открывается на каждую операцию — при небольшом
числе диалогов это надёжнее, чем держать постоянное подключение.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any


def _unwrap(data: Any) -> Any:
    """fastmcp оборачивает не-dict результаты в {"result": ...}."""
    if isinstance(data, dict) and set(data.keys()) == {"result"}:
        return data["result"]
    return data


class MCPClient:
    def __init__(self, url: str, timeout: float = 30.0):
        self.url = url
        self.timeout = timeout
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="mcp-client", daemon=True)
        self._thread.start()
        self._tools_cache: list[dict] | None = None

    def _run(self, coro):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(self.timeout)

    async def _list_tools(self):
        from fastmcp import Client
        async with Client(self.url) as client:
            return await client.list_tools()

    async def _call_tool(self, name: str, arguments: dict):
        from fastmcp import Client
        async with Client(self.url) as client:
            return await client.call_tool(name, arguments)

    def openai_tools(self, refresh: bool = False) -> list[dict]:
        """Схемы инструментов в формате OpenAI function calling."""
        if self._tools_cache is not None and not refresh:
            return self._tools_cache
        tools = self._run(self._list_tools())
        self._tools_cache = [{
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": (getattr(t, "input_schema", None)
                               or getattr(t, "inputSchema", None)
                               or {"type": "object", "properties": {}}),
            },
        } for t in tools]
        return self._tools_cache

    def call(self, name: str, arguments: dict | None = None) -> Any:
        """Вызов инструмента. Возвращает dict/list или
        {"error": ...} при сбое транспорта."""
        try:
            result = self._run(self._call_tool(name, arguments or {}))
        except Exception as e:
            return {"error": f"MCP недоступен или инструмент упал: {e}"}
        data = getattr(result, "data", None)
        if data is not None:
            return _unwrap(data)
        # fallback: текстовый контент
        content = getattr(result, "content", None) or []
        texts = [getattr(c, "text", "") for c in content]
        joined = "\n".join(t for t in texts if t)
        try:
            return _unwrap(json.loads(joined))
        except (json.JSONDecodeError, TypeError):
            return {"text": joined}

    def ping(self) -> bool:
        try:
            self.openai_tools(refresh=True)
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
