"""Клиент DeepSeek (OpenAI-совместимый API).

- Ключ — из переменной окружения DEEPSEEK_API_KEY (подхватывает config).
- Модель по умолчанию deepseek-v4-pro; алиасы deepseek-chat/deepseek-reasoner
  выведены из эксплуатации 24.07.2026 и не работают — не используйте их.
- Режим рассуждения — параметр запроса (thinking), рассуждения приходят в поле
  reasoning_content и в историю НЕ возвращаются (требование DeepSeek).
"""
from __future__ import annotations

import logging

from openai import OpenAI

import config

log = logging.getLogger(__name__)


class DeepSeekClient:
    def __init__(self):
        if not config.DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY не задан — ответы LLM недоступны")
        self._c = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

    def chat(self, messages: list[dict], tools: list[dict] | None = None):
        """Один вызов chat completions. Возвращает message (content, tool_calls)."""
        kwargs: dict = {
            "model": config.DEEPSEEK_MODEL,
            "messages": messages,
            "temperature": 0.2,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if config.DEEPSEEK_THINKING:
            # Если версия API отклонит параметр — выключите: DEEPSEEK_THINKING=0
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        resp = self._c.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning:
            log.info("reasoning: %d симв.", len(reasoning))
        return msg


def assistant_message_to_dict(msg) -> dict:
    """Сериализация ответа ассистента для истории: без reasoning_content."""
    d: dict = {"role": "assistant", "content": msg.content or ""}
    if getattr(msg, "tool_calls", None):
        d["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]
    return d
