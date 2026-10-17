"""MCP-сервер CRM: инструменты доступа к пользователям и тикетам.

Источник данных — через CRMProvider (по умолчанию JSON-файлы
в STORAGE_DIR). Транспорт:
  - streamable-http (по умолчанию, для docker-compose): порт MCP_PORT (8001)
  - stdio: MCP_TRANSPORT=stdio

Запуск:  python -m mcp_server.server
"""
from __future__ import annotations

import os

from fastmcp import FastMCP

from domain.crm import get_provider

mcp = FastMCP("support-crm")
_provider = get_provider()


@mcp.tool
def create_user(name: str, email: str, company: str = "",
                plan: str = "basic", product_version: str = "") -> dict:
    """Создать пользователя CRM. plan: basic | pro | enterprise.
    Email должен быть уникальным."""
    return _provider.create_user(name, email, company, plan,
                                 product_version)


@mcp.tool
def get_user(user_id: str) -> dict:
    """Вернуть пользователя по id (имя, email, тариф, версия продукта)."""
    u = _provider.get_user(user_id)
    return u if u is not None else {"error": f"Пользователь не найден: {user_id}"}


@mcp.tool
def find_user(email: str) -> dict:
    """Найти пользователя по email."""
    u = _provider.find_user_by_email(email)
    return u if u is not None else {"error": f"Пользователь не найден: {email}"}


@mcp.tool
def list_users() -> list[dict]:
    """Список всех пользователей."""
    return _provider.list_users()


@mcp.tool
def list_tickets(user_id: str | None = None, status: str | None = None) -> list[dict]:
    """Список тикетов. Фильтры: user_id и/или status
    (open | in_progress | resolved | closed)."""
    return _provider.list_tickets(user_id=user_id, status=status)


@mcp.tool
def get_ticket(ticket: str) -> dict:
    """Вернуть тикет по id или номеру (например, T-1001): тема, статус,
    приоритет, окружение, описание, история комментариев."""
    t = _provider.get_ticket(ticket)
    return t if t is not None else {"error": f"Тикет не найден: {ticket}"}


@mcp.tool
def add_ticket_comment(ticket: str, text: str,
                       author: str = "assistant") -> dict:
    """Добавить комментарий к тикету (по id или номеру)."""
    return _provider.add_ticket_comment(ticket, author, text)


@mcp.tool
def update_ticket_status(ticket: str, status: str) -> dict:
    """Сменить статус тикета: open | in_progress | resolved | closed."""
    return _provider.update_ticket_status(ticket, status)


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        port = int(os.environ.get("MCP_PORT", "8001"))
        host = os.environ.get("MCP_HOST", "0.0.0.0")
        mcp.run(transport="streamable-http", host=host, port=port)


if __name__ == "__main__":
    main()
