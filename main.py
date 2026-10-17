"""AI-ассистент поддержки пользователей (Flet, веб-режим).

Маршруты:
  /       — чат с ассистентом (идентификация → диалог → оценка)
  /admin  — администрирование (база знаний, CRM-данные, настройки)
  /logs   — журнал событий и статистика

Перед запуском приложения должен работать MCP-сервер CRM:
    python -m mcp_server.server           # порт 8001

Запуск приложения:
    export DEEPSEEK_API_KEY=sk-...
    python main.py                        # http://127.0.0.1:8550
Переменные окружения: APP_HOST, APP_PORT, MCP_URL, STORAGE_DIR,
EMBED_MODEL, DEEPSEEK_API_KEY.
"""
from __future__ import annotations

import os
import threading

import flet as ft

from ui import app_context as ctx
from ui import theme as T
from ui.admin_page import AdminPage
from ui.logs_page import LogsPage
from ui.user_page import UserPage

TITLE = "Ассистент поддержки «Контур.Учёт»"


def main(page: ft.Page) -> None:
    T.apply_theme(page)
    page.title = TITLE

    def nav_button(text: str, route: str) -> ft.TextButton:
        active = (page.route or "/").startswith(route) if route != "/" \
            else (page.route or "/") == "/"
        return ft.TextButton(
            content=ft.Text(text, size=14,
                            color=T.ORANGE_DARK if active else T.GRAY_TEXT,
                            weight=ft.FontWeight.W_600 if active
                            else ft.FontWeight.W_400),
            on_click=lambda e: page.navigate(route))

    def render() -> None:
        page.controls.clear()
        page.appbar = ft.AppBar(
            title=ft.Row([ft.Icon(ft.Icons.SUPPORT_AGENT, color=T.ORANGE),
                          ft.Text(TITLE)], spacing=8),
            bgcolor=ft.Colors.WHITE,
            actions=[nav_button("Чат", "/"),
                     nav_button("Администрирование", "/admin"),
                     nav_button("Логи", "/logs"),
                     ft.Container(width=12)],
        )
        route = page.route or "/"
        if route.startswith("/admin"):
            page.add(AdminPage(page).build())
        elif route.startswith("/logs"):
            page.add(LogsPage(page).build())
        else:
            page.add(UserPage(page).build())
        page.update()

    page.on_route_change = lambda e: render()
    render()


def _warmup_index() -> None:
    """Фоновая индексация базы знаний при старте (если индекс пуст)."""
    try:
        ctx.ensure_index()
        print("[warmup] индекс RAG:", ctx.index_status)
    except Exception as e:
        print("[warmup] ошибка индексации:", e)


if __name__ == "__main__":
    # Локальный запуск: MCP-сервер поднимаем автоматически, если не запущен.
    if ctx.ensure_mcp_server():
        print("[startup] MCP-сервер CRM доступен:", ctx.mcp.url)
    else:
        print("[startup] ВНИМАНИЕ: MCP-сервер недоступен (", ctx.mcp.url,
              "). Запустите вручную: python -m mcp_server.server")
    threading.Thread(target=_warmup_index, daemon=True).start()
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", "8550"))
    ft.run(main, view=ft.AppView.WEB_BROWSER, host=host, port=port,
           upload_dir=str(ctx.STORAGE_DIR / "uploads"))
