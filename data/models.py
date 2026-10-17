"""Модели данных ассистента поддержки.

Все сущности сериализуются в dict для JSON-хранилища.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime
from typing import Any


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


TICKET_STATUSES = ("open", "in_progress", "resolved", "closed")
TICKET_PRIORITIES = ("low", "normal", "high", "critical")
DIALOG_STATUSES = ("active", "closed")

# Модели DeepSeek, доступные в конфиге агента
AVAILABLE_MODELS = ["deepseek-v4-pro", "deepseek-flash"]

REASONING_EFFORTS = ("low", "high", "max")


@dataclass
class User:
    id: str
    name: str
    email: str
    company: str = ""
    plan: str = "basic"              # basic | pro | enterprise
    product_version: str = ""
    created_at: str = field(default_factory=now_iso)


@dataclass
class Ticket:
    id: str
    number: str                      # человекочитаемый номер, напр. T-1001
    user_id: str
    subject: str
    status: str = "open"             # open | in_progress | resolved | closed
    priority: str = "normal"         # low | normal | high | critical
    product_area: str = ""           # авторизация, оплата, интеграции...
    environment: str = ""            # ОС, браузер, версия приложения
    description: str = ""
    comments: list[dict] = field(default_factory=list)  # [{author, text, ts}]
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class Dialog:
    id: str
    user_id: str
    ticket_id: str = ""
    title: str = ""
    status: str = "active"           # active | closed
    messages: list[dict] = field(default_factory=list)  # см. new_message()
    created_at: str = field(default_factory=now_iso)
    closed_at: str = ""


def new_message(role: str, content: str, *, sources: list[dict] | None = None,
                tool_calls: list[str] | None = None,
                usage: dict | None = None) -> dict:
    """Сообщение диалога. sources — фрагменты RAG [{doc, score, snippet}],
    tool_calls — имена вызванных MCP-инструментов, usage — токены LLM."""
    return {
        "role": role,
        "content": content,
        "created_at": now_iso(),
        "sources": sources or [],
        "tool_calls": tool_calls or [],
        "usage": usage or {},
    }


@dataclass
class Feedback:
    id: str
    dialog_id: str
    user_id: str
    rating: int                      # 1..5
    comment: str = ""
    created_at: str = field(default_factory=now_iso)


@dataclass
class KBDocument:
    id: str
    name: str
    filename: str
    chunk_count: int = 0
    status: str = "indexed"          # indexed | error
    error: str = ""
    uploaded_at: str = field(default_factory=now_iso)


@dataclass
class AgentConfig:
    """Конфигурация агента поддержки, редактируется в админке."""
    id: str
    name: str = "Ассистент поддержки"
    model: str = "deepseek-v4-pro"
    temperature: float = 0.3
    max_tokens: int = 8192
    thinking: bool = False           # для поддержки thinking обычно избыточен
    reasoning_effort: str = "low"    # применяется при thinking=True
    rag_top_k: int = 4
    rag_threshold: float = 0.55      # минимальный косинус для включения фрагмента
    history_limit: int = 12          # сколько последних сообщений уходит в LLM
    system_prompt_extra: str = ""


def to_dict(obj: Any) -> dict:
    return asdict(obj)


def from_dict(cls, data: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})
