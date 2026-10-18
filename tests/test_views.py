"""Регрессионные тесты: update() у контрола вне страницы.

Flet падает с RuntimeError 'Control must be added to the page first', если
view обновляется, будучи не на странице (гонка: задача в чате завершилась,
когда пользователь переключил вкладку). Все view обязаны переживать такие
вызовы без исключений.
"""
import json

import pytest  # noqa: F401  (фикстуры tmp_path)

from ui.admin_view import AdminView
from ui.chat_view import ChatView
from ui.logs_view import LogsView


def test_logs_refresh_without_page_empty(tmp_path):
    v = LogsView(tmp_path / "changes.jsonl")
    v.refresh()            # раньше падало: Control must be added to the page first
    v.mounted_refresh()    # контрол не смонтирован — должно молча пропустить


def test_logs_refresh_without_page_with_records(tmp_path):
    log = tmp_path / "changes.jsonl"
    rec = {"ts": "2026-10-18 10:00:00", "action": "overwritten",
           "path": "src/a.bsl", "summary": "правка", "diff": "+x\n"}
    log.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    v = LogsView(log)
    v.refresh()
    assert "перезаписан" in v._stats.value


def test_admin_refresh_without_page():
    AdminView().refresh()


def test_chat_update_without_page():
    c = ChatView()
    c._safe_update()
    c._set_busy(True)
    assert c._busy is True
    c._set_busy(False)
    assert c._busy is False
