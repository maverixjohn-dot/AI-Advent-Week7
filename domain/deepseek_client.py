"""Клиент DeepSeek API (OpenAI-совместимый интерфейс).

Ключ читается из переменной окружения DEEPSEEK_API_KEY.
Актуальные модели: deepseek-v4-pro (по ТЗ), deepseek-flash.
(Перенесено из проекта «агент_спецификаций_1с», адаптировано.)
"""
from __future__ import annotations

import os
from typing import Any

BASE_URL = "https://api.deepseek.com"


class DeepSeekError(Exception):
    pass


class DeepSeekClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise DeepSeekError(
                "Не задан ключ API: переменная окружения DEEPSEEK_API_KEY пуста. "
                "Задайте её перед запуском приложения.")
        try:
            from openai import OpenAI
        except ImportError as e:
            raise DeepSeekError("Не установлен пакет openai: pip install openai") from e
        self._client = OpenAI(api_key=self.api_key, base_url=BASE_URL)
        return self._client

    def chat(self, model: str, messages: list[dict[str, Any]],
             temperature: float, max_tokens: int,
             tools: list[dict] | None = None,
             thinking: bool = False, reasoning_effort: str = "low"):
        """Один вызов chat completions. Возвращает объект ответа openai.

        thinking/reasoning_effort — параметры thinking mode DeepSeek:
        thinking через extra_body, reasoning_effort отправляется
        только при включённом thinking.
        """
        client = self._ensure_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if thinking else "disabled"}}
        if thinking:
            kwargs["reasoning_effort"] = reasoning_effort
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            raise DeepSeekError(f"Ошибка вызова DeepSeek API: {e}") from e
