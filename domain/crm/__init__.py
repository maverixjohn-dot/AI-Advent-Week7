"""Фабрика CRM-провайдера.

CRM_PROVIDER=json (по умолчанию) — JSON-файлы в STORAGE_DIR.
Чтобы подключить реальную CRM: реализуйте CRMProvider
(domain/crm/base.py) и добавьте ветку в get_provider().
"""
from __future__ import annotations

import os
from pathlib import Path

from domain.crm.base import CRMProvider


def default_storage_dir() -> Path:
    return Path(os.environ.get(
        "STORAGE_DIR",
        str(Path(__file__).resolve().parents[2] / "storage")))


def get_provider(storage_dir: str | Path | None = None) -> CRMProvider:
    kind = os.environ.get("CRM_PROVIDER", "json")
    if kind == "json":
        from data.storage import JsonStore
        from data.repositories import UserRepo, TicketRepo
        from domain.crm.json_provider import JsonCRMProvider
        store = JsonStore(storage_dir or default_storage_dir())
        # На случай, если MCP-сервер стартовал раньше приложения —
        # демо-данные должны существовать.
        from data import seeds
        seeds.ensure_seeded(store)
        return JsonCRMProvider(UserRepo(store), TicketRepo(store))
    raise ValueError(f"Неизвестный CRM_PROVIDER: {kind}")
