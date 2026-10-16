"""Каркас приложения: навигация Чат / Администрирование."""
from __future__ import annotations

import asyncio
import logging

import flet as ft

import config
from agent.assistant import Assistant
from ui import theme
from ui.admin_view import AdminView
from ui.chat_view import ChatView

log = logging.getLogger(__name__)


async def main(page: ft.Page):
    page.title = "Ассистент разработчика 1С"
    theme.apply(page)
    try:
        page.window.width, page.window.height = 1100, 760
    except Exception:
        pass  # в web-режиме размер окна не управляется

    problems = config.validate()
    if any("DUMP_ROOT" in p for p in problems):
        page.add(ft.Container(
            ft.Column([ft.Text("Репозиторий выгрузки не найден", size=20,
                               color=theme.ORANGE_DARK)]
                      + [ft.Text("• " + p, color=theme.TEXT) for p in problems]
                      + [ft.Text("Заполните .env по образцу .env.example и перезапустите.",
                                 color=theme.TEXT_DIM)]),
            padding=40))
        return

    assistant = Assistant()
    chat = ChatView(assistant)
    admin = AdminView()

    content = ft.Container(content=chat, expand=True, padding=theme.pad_all(12))
    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=90,
        indicator_color=theme.ORANGE_SOFT,
        selected_label_text_style=ft.TextStyle(color=theme.ORANGE_DARK),
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.CHAT_OUTLINED,
                                         selected_icon=ft.Icons.CHAT, label="Чат"),
            ft.NavigationRailDestination(icon=ft.Icons.SETTINGS_OUTLINED,
                                         selected_icon=ft.Icons.SETTINGS,
                                         label="Админ"),
        ],
        on_change=lambda e: _swap(e.control.selected_index),
    )

    def _swap(index: int):
        content.content = chat if index == 0 else admin
        page.update()  # сначала контрол попадает на страницу
        if index == 1:
            admin.refresh()  # update() внутри refresh требует смонтированный контрол

    page.add(ft.Row([rail, ft.VerticalDivider(width=1, color=theme.BORDER), content],
                    expand=True, spacing=0))

    # некритичные проблемы (например, нет ключа DeepSeek) — баннер, не блокировка
    if problems:
        page.show_dialog(ft.SnackBar(
            ft.Text("Внимание: " + "; ".join(problems)),
            bgcolor=theme.ORANGE_DARK, duration=15000))

    page.update()  # применить размер окна и начальное состояние

    def _disconnect(e):
        try:
            asyncio.get_running_loop().create_task(assistant.close())
        except RuntimeError:
            pass

    page.on_disconnect = _disconnect
