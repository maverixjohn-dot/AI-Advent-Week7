"""Репозитории — единственная точка доступа к данным.

Слои domain и ui работают только через эти классы, что позволит
позднее заменить JSON на SQLite без их изменения.
"""
from __future__ import annotations

from data.models import (
    User, Ticket, Dialog, Feedback, KBDocument, AgentConfig,
    to_dict, from_dict, new_id, now_iso, TICKET_STATUSES,
)
from data.storage import JsonStore


class _ListRepo:
    """Базовый репозиторий для сущностей в одном JSON-файле-списке."""

    filename = ""
    cls = None

    def __init__(self, store: JsonStore):
        self.store = store

    def _all(self) -> list[dict]:
        return self.store.read(self.filename, default=[])

    def _save_all(self, items: list[dict]) -> None:
        self.store.write(items, self.filename)

    def list(self) -> list:
        return [from_dict(self.cls, d) for d in self._all()]

    def get(self, item_id: str):
        for d in self._all():
            if d.get("id") == item_id:
                return from_dict(self.cls, d)
        return None

    def upsert(self, obj) -> None:
        items = self._all()
        data = to_dict(obj)
        for i, d in enumerate(items):
            if d.get("id") == data["id"]:
                items[i] = data
                break
        else:
            items.append(data)
        self._save_all(items)

    def delete(self, item_id: str) -> None:
        self._save_all([d for d in self._all() if d.get("id") != item_id])

    def count(self) -> int:
        return len(self._all())


class UserRepo(_ListRepo):
    filename = "users.json"
    cls = User

    def find_by_email(self, email: str) -> User | None:
        email = (email or "").strip().lower()
        for u in self.list():
            if u.email.lower() == email:
                return u
        return None


class TicketRepo(_ListRepo):
    filename = "tickets.json"
    cls = Ticket

    def get_by_ref(self, ref: str) -> Ticket | None:
        """Тикет по id или по человекочитаемому номеру (T-1001)."""
        ref = (ref or "").strip()
        for t in self.list():
            if t.id == ref or t.number.upper() == ref.upper():
                return t
        return None

    def filter(self, user_id: str | None = None,
               status: str | None = None) -> list[Ticket]:
        out = self.list()
        if user_id:
            out = [t for t in out if t.user_id == user_id]
        if status:
            out = [t for t in out if t.status == status]
        return sorted(out, key=lambda t: t.created_at)

    def add_comment(self, ticket_id: str, author: str, text: str) -> Ticket | None:
        t = self.get_by_ref(ticket_id)
        if t is None:
            return None
        t.comments.append({"author": author, "text": text, "ts": now_iso()})
        t.updated_at = now_iso()
        self.upsert(t)
        return t

    def set_status(self, ticket_id: str, status: str) -> Ticket | None:
        if status not in TICKET_STATUSES:
            raise ValueError(f"Недопустимый статус: {status}. "
                             f"Допустимые: {', '.join(TICKET_STATUSES)}")
        t = self.get_by_ref(ticket_id)
        if t is None:
            return None
        t.status = status
        t.updated_at = now_iso()
        self.upsert(t)
        return t


class DialogRepo(_ListRepo):
    filename = "dialogs.json"
    cls = Dialog

    def add_message(self, dialog_id: str, message: dict) -> None:
        d = self.get(dialog_id)
        if d is None:
            return
        d.messages.append(message)
        self.upsert(d)

    def close(self, dialog_id: str) -> Dialog | None:
        d = self.get(dialog_id)
        if d is None:
            return None
        d.status = "closed"
        d.closed_at = now_iso()
        self.upsert(d)
        return d


class FeedbackRepo(_ListRepo):
    filename = "feedback.json"
    cls = Feedback

    def for_dialog(self, dialog_id: str) -> Feedback | None:
        for f in self.list():
            if f.dialog_id == dialog_id:
                return f
        return None

    def average_rating(self) -> float | None:
        items = self.list()
        if not items:
            return None
        return round(sum(f.rating for f in items) / len(items), 2)


class KBRepo(_ListRepo):
    filename = "kb_documents.json"
    cls = KBDocument

    def by_filename(self, filename: str) -> KBDocument | None:
        for d in self.list():
            if d.filename == filename:
                return d
        return None


class AgentConfigRepo(_ListRepo):
    filename = "agent_config.json"
    cls = AgentConfig

    def get_or_create_default(self) -> AgentConfig:
        existing = self.list()
        if existing:
            return existing[0]
        cfg = AgentConfig(id=new_id())
        self.upsert(cfg)
        return cfg


class LogRepo:
    """Журнал событий в JSONL: дёшево писать, удобно читать хвост."""

    def __init__(self, store: JsonStore):
        self.store = store

    def log(self, event: str, **kwargs) -> dict:
        rec = {"id": new_id(), "ts": now_iso(), "event": event, **kwargs}
        self.store.append_jsonl(rec, "logs.jsonl")
        return rec

    def list(self, limit: int = 300, prefix: str | None = None) -> list[dict]:
        rows = self.store.read_jsonl("logs.jsonl")
        if prefix:
            rows = [r for r in rows if str(r.get("event", "")).startswith(prefix)]
        return rows[-limit:][::-1]

    def clear(self) -> None:
        self.store.clear_jsonl("logs.jsonl")
