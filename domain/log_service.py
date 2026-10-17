"""Сервис логирования: пишет в LogRepo и рассылает события подписчикам
(страница «Логи» может обновляться в реальном времени)."""
from __future__ import annotations

from typing import Callable

from data.repositories import LogRepo


class LogService:
    def __init__(self, log_repo: LogRepo):
        self.repo = log_repo
        self._subscribers: list[Callable[[dict], None]] = []

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        self._subscribers.append(fn)

    def log(self, event: str, **kwargs) -> dict:
        rec = self.repo.log(event, **kwargs)
        for fn in list(self._subscribers):
            try:
                fn(rec)
            except Exception:
                pass
        return rec
