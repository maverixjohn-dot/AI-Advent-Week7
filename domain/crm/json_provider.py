"""JSON-реализация CRMProvider поверх репозиториев."""
from __future__ import annotations

from data.models import User, to_dict, new_id, TICKET_STATUSES
from data.repositories import UserRepo, TicketRepo
from domain.crm.base import CRMProvider

PLANS = ("basic", "pro", "enterprise")


class JsonCRMProvider(CRMProvider):
    def __init__(self, users: UserRepo, tickets: TicketRepo):
        self.users = users
        self.tickets = tickets

    def create_user(self, name: str, email: str, company: str = "",
                    plan: str = "basic",
                    product_version: str = "") -> dict:
        name = (name or "").strip()
        email = (email or "").strip().lower()
        if not name:
            return {"error": "Пустое имя пользователя"}
        if not email or "@" not in email:
            return {"error": f"Некорректный email: {email!r}"}
        if plan not in PLANS:
            return {"error": f"Недопустимый тариф '{plan}'. "
                             f"Допустимые: {', '.join(PLANS)}"}
        if self.users.find_by_email(email):
            return {"error": f"Пользователь с email {email} "
                             "уже существует"}
        u = User(id=new_id(), name=name, email=email,
                 company=(company or "").strip(), plan=plan,
                 product_version=(product_version or "").strip())
        self.users.upsert(u)
        return to_dict(u)

    def get_user(self, user_id: str) -> dict | None:
        u = self.users.get(user_id)
        return to_dict(u) if u else None

    def find_user_by_email(self, email: str) -> dict | None:
        u = self.users.find_by_email(email)
        return to_dict(u) if u else None

    def list_users(self) -> list[dict]:
        return [to_dict(u) for u in self.users.list()]

    def list_tickets(self, user_id: str | None = None,
                     status: str | None = None) -> list[dict]:
        return [to_dict(t) for t in self.tickets.filter(user_id, status)]

    def get_ticket(self, ticket_ref: str) -> dict | None:
        t = self.tickets.get_by_ref(ticket_ref)
        return to_dict(t) if t else None

    def add_ticket_comment(self, ticket_ref: str, author: str, text: str) -> dict:
        t = self.tickets.add_comment(ticket_ref, author, text)
        if t is None:
            return {"error": f"Тикет не найден: {ticket_ref}"}
        return to_dict(t)

    def update_ticket_status(self, ticket_ref: str, status: str) -> dict:
        if status not in TICKET_STATUSES:
            return {"error": f"Недопустимый статус '{status}'. "
                             f"Допустимые: {', '.join(TICKET_STATUSES)}"}
        t = self.tickets.set_status(ticket_ref, status)
        if t is None:
            return {"error": f"Тикет не найден: {ticket_ref}"}
        return to_dict(t)
