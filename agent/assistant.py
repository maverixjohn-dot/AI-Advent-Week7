"""Агентский цикл код-ассистента 1С: задача -> инструменты -> результат.

Пользователь ставит задачу на уровне цели («найди, где используется X»,
«обнови документацию по изменениям») — ассистент сам решает, какие файлы
читать и что менять.

LLM-абстракция: любой клиент с методом chat(messages, tools) -> message
(у message — .content и .tool_calls). Это позволяет подменять DeepSeekClient
моком в демо и тестах без API-ключа.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

import config
from .fs_tools import FileTools
from .guard import GuardError
from .llm_client import DeepSeekClient, assistant_message_to_dict
from .prompts import SYSTEM_PROMPT

log = logging.getLogger(__name__)

# Вопрос аналитику: (вопрос) -> ответ строкой
AskFn = Callable[[str], str]


def _tool_schema(name: str, description: str, properties: dict,
                 required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


TOOLS = [
    _tool_schema("list_files", "Список файлов и каталогов проекта (рекурсивно)", {
        "subdir": {"type": "string", "description": "Подкаталог от корня, по умолчанию '.'"},
        "mask": {"type": "string", "description": "Glob-маска имени файла, напр. *.bsl или *.xml"},
    }, []),
    _tool_schema("read_file", "Прочитать файл проекта построчно", {
        "path": {"type": "string", "description": "Путь относительно корня проекта"},
        "offset": {"type": "integer", "description": "С какой строки (с 1), по умолчанию 1"},
        "limit": {"type": "integer", "description": "Сколько строк, по умолчанию 400"},
    }, ["path"]),
    _tool_schema("search_files", "Поиск подстроки или regex по содержимому файлов проекта (где используется объект, API, процедура)", {
        "query": {"type": "string", "description": "Что ищем (подстрока или regex)"},
        "subdir": {"type": "string", "description": "Подкаталог, по умолчанию '.'"},
        "mask": {"type": "string", "description": "Glob-маска файлов, по умолчанию '*'"},
        "context": {"type": "integer", "description": "Строк контекста вокруг совпадения, по умолчанию 2"},
        "regex": {"type": "boolean", "description": "Трактовать query как regex, по умолчанию false"},
    }, ["query"]),
    _tool_schema("write_file", "Создать файл или перезаписать целиком. Перезапись существующего требует подтверждения аналитика. dry_run=true — показать diff без записи", {
        "path": {"type": "string", "description": "Путь относительно корня проекта"},
        "content": {"type": "string", "description": "Полное новое содержимое файла"},
        "change_summary": {"type": "string", "description": "Краткое описание доработки по-русски — уйдёт в журнал README"},
        "dry_run": {"type": "boolean", "description": "Только показать diff, не записывать"},
    }, ["path", "content", "change_summary"]),
    _tool_schema("append_to_file", "Дописать в конец существующего файла (changelog, ADR-лог)", {
        "path": {"type": "string", "description": "Путь относительно корня проекта"},
        "content": {"type": "string", "description": "Текст для добавления в конец"},
        "change_summary": {"type": "string", "description": "Краткое описание доработки по-русски — уйдёт в журнал README"},
        "dry_run": {"type": "boolean", "description": "Только показать diff, не записывать"},
    }, ["path", "content", "change_summary"]),
    _tool_schema("ask_analyst", "Задать вопрос человеку-аналитику и дождаться ответа (перед опасными или неоднозначными действиями)", {
        "question": {"type": "string", "description": "Вопрос аналитику, по-русски"},
    }, ["question"]),
]


class CodeAssistant:
    """Код-ассистент: LLM + файловые инструменты + инварианты.

    on_event(kind, payload) — необязательный колбэк прогресса для UI:
      "tool_call"   {"name": str, "args": dict}        — перед вызовом инструмента
      "tool_result" {"name": str, "preview": str}      — после вызова (первые ~300 симв.)
      "answer"      {"text": str}                      — финальный ответ
    Вызывается из рабочего потока run_task; UI обязан сам маршаллить в свой поток.
    """

    def __init__(self, tools: FileTools, llm=None, ask: AskFn | None = None,
                 on_event: Callable[[str, dict], None] | None = None):
        self.tools = tools
        self._llm = llm  # None -> DeepSeekClient (лениво)
        self._ask: AskFn = ask or (lambda q: "аналитик недоступен")
        self._on_event = on_event or (lambda _k, _p: None)
        self._history: list[dict] = []

    # ---------------------------------------------------------------- tools
    def _dispatch(self, name: str, args: dict) -> str:
        try:
            if name == "list_files":
                return self.tools.list_files(**args)
            if name == "read_file":
                return self.tools.read_file(**args)
            if name == "search_files":
                return self.tools.search_files(**args)
            if name == "write_file":
                return self.tools.write_file(**args)
            if name == "append_to_file":
                return self.tools.append_to_file(**args)
            if name == "ask_analyst":
                return self._ask(args.get("question", ""))
            return f"Неизвестный инструмент: {name}"
        except GuardError as e:
            log.warning("Инвариант: %s", e)
            return f"ОТКАЗ (инвариант): {e}"
        except TypeError as e:
            return f"Ошибка параметров инструмента {name}: {e}"
        except Exception as e:  # инструмент упал — отдаём ошибку модели
            log.exception("Инструмент %s упал", name)
            return f"Ошибка инструмента {name}: {e}"

    # ---------------------------------------------------------------- цикл
    def run_task(self, task: str) -> str:
        """Выполнить одну задачу уровня цели. Возвращает финальный ответ."""
        if self._llm is None:
            self._llm = DeepSeekClient()
        self._history.append({"role": "user", "content": task})
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self._history

        for _ in range(config.MAX_ITER):
            msg = self._llm.chat(messages, tools=TOOLS)
            if not getattr(msg, "tool_calls", None):
                answer = msg.content or "(пустой ответ модели)"
                self._history.append({"role": "assistant", "content": answer})
                self._on_event("answer", {"text": answer})
                return answer
            messages.append(assistant_message_to_dict(msg))
            for tc in msg.tool_calls:
                try:
                    t_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    t_args = {}
                log.info("LLM вызывает %s %s", tc.function.name,
                         {k: (v[:80] + "…" if isinstance(v, str) and len(v) > 80 else v)
                          for k, v in t_args.items()})
                self._on_event("tool_call", {"name": tc.function.name, "args": t_args})
                result = self._dispatch(tc.function.name, t_args)
                self._on_event("tool_result", {"name": tc.function.name,
                                               "preview": result[:300]})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        return (f"Превышен лимит итераций ({config.MAX_ITER}) — задача не завершена. "
                f"Разбейте её на части или увеличьте CA1C_MAX_ITER.")
