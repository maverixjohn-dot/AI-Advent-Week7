"""Абстракция провайдера CRM.

Агент и MCP-сервер работают с CRM только через этот интерфейс.
Сейчас реализован JSON-провайдер (файлы users.json / tickets.json);
для подключения реальной CRM достаточно реализовать CRMProvider
и зарегистрировать его в domain/crm/__init__.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class CRMProvider(ABC):
    """Интерфейс источника данных о пользователях и тикетах.

    Все методы возвращают JSON-сериализуемые dict / list[dict] —
    они напрямую отдаются через MCP-инструменты.
    """

    @abstractmethod
    def create_user(self, name: str, email: str, company: str = "",
                    plan: str = "basic",
                    product_version: str = "") -> dict:
        """Создать пользователя. Возвращает созданного или {"error": ...}."""

    @abstractmethod
    def get_user(self, user_id: str) -> dict | None:
        """Пользователь по id. None, если не найден."""

    @abstractmethod
    def find_user_by_email(self, email: str) -> dict | None:
        """Пользователь по email (регистр не важен)."""

    @abstractmethod
    def list_users(self) -> list[dict]:
        """Все пользователи."""

    @abstractmethod
    def list_tickets(self, user_id: str | None = None,
                     status: str | None = None) -> list[dict]:
        """Тикеты с опциональной фильтрацией по пользователю и статусу."""

    @abstractmethod
    def get_ticket(self, ticket_ref: str) -> dict | None:
        """Тикет по id или номеру (T-1001)."""

    @abstractmethod
    def add_ticket_comment(self, ticket_ref: str, author: str, text: str) -> dict:
        """Добавить комментарий к тикету. Возвращает обновлённый тикет
        или {"error": ...}."""

    @abstractmethod
    def update_ticket_status(self, ticket_ref: str, status: str) -> dict:
        """Сменить статус тикета. Возвращает обновлённый тикет
        или {"error": ...}."""
