"""Агент ассистента разработчика 1С.

- Свободные вопросы -> DeepSeek с tool calling -> инструменты MCP-сервера.
- Slash-команды -> детерминированный вызов того же инструмента без LLM
  (мгновенно, без расхода токенов).
- /help — справка; /reindex — переиндексация с последующим перезапуском MCP-сервера
  (тот кэширует индекс в памяти).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from fastmcp import Client

import config
from agent.llm_client import DeepSeekClient, assistant_message_to_dict

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — ассистент разработчика конфигурации 1С «Целеполагание»
(самописная конфигурация, управляемое приложение, платформа 8.3.21+, код на русском).

Правила работы:
- Вопросы о структуре конфигурации (какие есть объекты, реквизиты, состав объекта) —
  отвечай через инструменты objects_tree / object_info / objects_list. Ничего не выдумывай.
- Вопросы о смысле, логике, документации и текстах модулей — через rag_search.
- Состояние репозитория (ветка, изменения, список файлов) — через
  get_current_branch / git_diff / list_files.
- Отвечай по-русски, коротко и по делу. Имена объектов приводи точно, как в конфигурации
  (например, Документ.ФинансовыйФакт).
- Если данных для ответа не хватает — скажи прямо и предложи, что сделать
  (переиндексация, добавить документацию, уточнить вопрос).
"""

_HELP = r"""**Команды ассистента**

| Команда | Что делает |
|---|---|
| /help | Эта справка. Вопросы о проекте можно задавать и свободным текстом |
| /tree | Дерево объектов конфигурации по подсистемам |
| /object \<имя\> | Состав объекта: реквизиты, табличные части, формы, модули. Пример: `/object ФинансовыйФакт` |
| /objects [маска] [тип=...] [подсистема=...] | Объекты по фильтру. Примеры: `/objects *Финанс*`, `/objects тип=Документ` |
| /branch | Текущая ветка git |
| /diff [файл] | Изменения в рабочем дереве (целиком или по файлу) |
| /reindex [full] | Переиндексация RAG (инкрементальная или полная) |

Всё остальное — свободный вопрос: ассистент сам вызовет нужные инструменты
(структура, RAG по документации и коду, git)."""


def _tool_schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


TOOLS = [
    _tool_schema("get_current_branch", "Текущая git-ветка репозитория выгрузки конфигурации", {}, []),
    _tool_schema("git_diff", "Diff изменений в репозитории выгрузки", {
        "file_path": {"type": "string", "description": "Путь к файлу относительно корня репозитория; пусто — весь diff"},
        "staged": {"type": "boolean", "description": "Только проиндексированные изменения"},
    }, []),
    _tool_schema("list_files", "Список файлов репозитория выгрузки", {
        "subdir": {"type": "string", "description": "Подкаталог"},
        "mask": {"type": "string", "description": "Glob-маска имени файла, напр. *.bsl"},
    }, []),
    _tool_schema("objects_tree", "Дерево объектов конфигурации 1С по подсистемам", {}, []),
    _tool_schema("object_info", "Состав объекта метаданных: реквизиты, табличные части, формы, макеты, модули, движения", {
        "name": {"type": "string", "description": "Имя объекта: 'ФинансовыйФакт' или 'Документ.ФинансовыйФакт'"},
    }, ["name"]),
    _tool_schema("objects_list", "Список объектов конфигурации по фильтру", {
        "object_type": {"type": "string", "description": "Тип: Catalog/Справочник, Document/Документ и т.д."},
        "name_mask": {"type": "string", "description": "Glob-маска имени, напр. *Финанс*"},
        "subsystem": {"type": "string", "description": "Имя подсистемы"},
    }, []),
    _tool_schema("rag_search", "Семантический поиск по документации, карточкам объектов и коду модулей конфигурации", {
        "query": {"type": "string", "description": "Поисковый запрос на естественном языке"},
        "top_k": {"type": "integer", "description": "Сколько фрагментов вернуть (по умолчанию 5)"},
    }, ["query"]),
]

MAX_ITER = 8


class Assistant:
    def __init__(self):
        self._llm: DeepSeekClient | None = None
        self._mcp: Client | None = None
        self._history: list[dict] = []

    # --- MCP ---
    async def _mcp_client(self) -> Client:
        if self._mcp is None:
            # env передаём явно: fastmcp без него даёт subprocess урезанное окружение
            # (без HOME падает импорт пакетов из ~/.local)
            cfg_ = {"mcpServers": {"assistant-1c": {
                "command": sys.executable,
                "args": ["-m", "mcp_server.server"],
                "cwd": str(config.BASE_DIR),
                "env": dict(os.environ),
            }}}
            self._mcp = Client(cfg_)
            await self._mcp.__aenter__()
            log.info("MCP-сервер поднят (stdio)")
        return self._mcp

    async def close(self):
        if self._mcp is not None:
            await self._mcp.__aexit__(None, None, None)
            self._mcp = None

    async def call_tool(self, tool: str, args: dict) -> str:
        client = await self._mcp_client()
        result = await client.call_tool(tool, args)
        return result.content[0].text

    # --- slash-команды ---
    async def slash(self, line: str) -> str:
        cmd, _, rest = line.partition(" ")
        cmd, rest = cmd.lower(), rest.strip()

        if cmd == "/help":
            return _HELP
        if cmd == "/branch":
            return await self.call_tool("get_current_branch", {})
        if cmd == "/tree":
            return await self.call_tool("objects_tree", {})
        if cmd == "/object":
            if not rest:
                return "Укажите объект: `/object ФинансовыйФакт`"
            return await self.call_tool("object_info", {"name": rest})
        if cmd == "/objects":
            args: dict = {}
            for token in rest.split():
                if "=" in token:
                    k, v = token.split("=", 1)
                    key = {"тип": "object_type", "маска": "name_mask",
                           "подсистема": "subsystem"}.get(k.lower())
                    if key:
                        args[key] = v
                else:
                    args["name_mask"] = token
            return await self.call_tool("objects_list", args)
        if cmd == "/diff":
            return await self.call_tool("git_diff", {"file_path": rest})
        if cmd == "/reindex":
            return await self._reindex(full=(rest.lower() == "full"))
        return f"Неизвестная команда `{cmd}`. Справка: /help"

    async def _reindex(self, full: bool) -> str:
        args = [sys.executable, "-m", "indexer.indexer"] + (["--full"] if full else [])
        log.info("Запуск переиндексации: %s", args)
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(config.BASE_DIR),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.error("Индексация упала: %s", stderr.decode()[-2000:])
            return f"Переиндексация завершилась с ошибкой:\n```\n{stderr.decode()[-1500:]}\n```"
        # MCP-сервер кэширует индекс — перезапускаем
        await self.close()
        stats = json.loads(stdout.decode())
        return ("Переиндексация выполнена:\n"
                f"- объектов: {stats['objects']}, чанков всего: {stats['chunks_total']}, "
                f"переиндексировано: {stats['chunks_reindexed']}\n"
                f"- модель эмбеддингов: {stats['embed_model']}, время: {stats['duration_sec']} с")

    # --- свободный диалог ---
    async def ask(self, text: str) -> str:
        if self._llm is None:
            self._llm = DeepSeekClient()
        self._history.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self._history

        for _ in range(MAX_ITER):
            msg = self._llm.chat(messages, tools=TOOLS)
            if not getattr(msg, "tool_calls", None):
                answer = msg.content or "(пустой ответ модели)"
                self._history.append({"role": "assistant", "content": answer})
                return answer
            messages.append(assistant_message_to_dict(msg))
            for tc in msg.tool_calls:
                try:
                    t_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    t_args = {}
                log.info("LLM вызывает %s %s", tc.function.name, t_args)
                try:
                    result = await self.call_tool(tc.function.name, t_args)
                except Exception as e:  # инструмент упал — отдаём ошибку модели
                    log.exception("Инструмент %s упал", tc.function.name)
                    result = f"Ошибка инструмента: {e}"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        return "Превышен лимит итераций агента — попробуйте переформулировать вопрос."
