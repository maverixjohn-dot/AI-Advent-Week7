"""Мок LLM для демо и тестов без API-ключа.

Воспроизводит интерфейс DeepSeekClient.chat(): принимает messages/tools,
возвращает message с .content и .tool_calls по заранее заданному скрипту.
Скрипт — список шагов; каждый шаг либо вызовы инструментов, либо финальный
текст. Это НЕ эмуляция «интеллекта»: демо показывает механику агентского
цикла (инструменты, инварианты, подтверждения, журнал), качество рассуждений
зависит от реальной модели.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Fn:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    function: _Fn
    type: str = "function"


@dataclass
class _Message:
    content: str | None = None
    tool_calls: list[_ToolCall] | None = None


def tool_step(calls: list[tuple[str, dict]]) -> dict:
    """Шаг скрипта: вызовы инструментов [(имя, аргументы), ...]."""
    return {"calls": calls}


def text_step(text: str) -> dict:
    """Шаг скрипта: финальный текстовый ответ."""
    return {"text": text}


class MockLLM:
    def __init__(self, script: list[dict]):
        self._script = list(script)
        self.calls_log: list[tuple[str, dict]] = []
        self._n = 0

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Any:
        if self._n >= len(self._script):
            return _Message(content="(скрипт мока исчерпан)")
        step = self._script[self._n]
        self._n += 1
        if "text" in step:
            return _Message(content=step["text"])
        tcs = []
        for i, (name, args) in enumerate(step["calls"]):
            self.calls_log.append((name, args))
            tcs.append(_ToolCall(id=f"mock_{self._n}_{i}",
                                 function=_Fn(name, json.dumps(args, ensure_ascii=False))))
        return _Message(tool_calls=tcs)
