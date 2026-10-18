"""Каркас UI: шапка 1С + навигация Чат / Журнал / Администрирование."""
from __future__ import annotations

import logging

import flet as ft

import config
from agent.assistant import CodeAssistant
from agent.fs_tools import FileTools
from agent.guard import WorkspaceGuard
from ui import theme
from ui.admin_view import AdminView
from ui.chat_view import ChatView
from ui.logs_view import LogsView

log = logging.getLogger(__name__)


def _header() -> ft.Control:
    return ft.Container(
        ft.Row([
            theme.logo_1c(38),
            ft.Column([
                ft.Text("Код-ассистент 1С", size=17, weight=ft.FontWeight.BOLD,
                        color=theme.TEXT),
                ft.Text(f"эксперт-разработчик • {config.DEEPSEEK_MODEL}",
                        size=11, color=theme.TEXT_DIM),
            ], spacing=0, tight=True),
            ft.Container(expand=True),
            ft.Text("аналитик ставит задачи — разработчик правит файлы",
                    size=11, color=theme.TEXT_DIM, italic=True),
        ], spacing=12),
        bgcolor=theme.YELLOW,
        border=ft.Border(bottom=ft.BorderSide(2, theme.YELLOW_EDGE)),
        padding=theme.pad_sym(16, 8),
    )


def _config_error(page: ft.Page, problems: list[str]) -> None:
    page.add(ft.Container(
        ft.Column([
            theme.logo_1c(48),
            ft.Text("Рабочая директория не настроена", size=20,
                    color=theme.RED_DARK),
            *[ft.Text("• " + p, color=theme.TEXT) for p in problems],
            ft.Text("Заполните .env по образцу .env.example "
                    "(CA1C_WORKSPACE_ROOT, DEEPSEEK_API_KEY) и перезапустите.",
                    color=theme.TEXT_DIM),
        ], spacing=10, tight=True),
        padding=40))


async def main(page: ft.Page):
    page.title = "Код-ассистент 1С"
    theme.apply(page)
    try:
        page.window.width, page.window.height = 1150, 800
    except Exception:
        pass  # в web-режиме размер окна не управляется

    problems = config.validate()
    if any("CA1C_WORKSPACE_ROOT" in p for p in problems):
        _config_error(page, problems)
        return

    logs = LogsView(config.CHANGES_LOG)
    chat = ChatView(on_task_done=lambda: logs.mounted_refresh())

    # Ассистент: подтверждения и вопросы — через диалоги чата,
    # журнал изменений — JSONL для страницы «Журнал».
    guard = WorkspaceGuard(config.WORKSPACE_ROOT)
    tools = FileTools(guard, confirm=chat.confirm_ui, change_log=config.CHANGES_LOG)
    chat.assistant = CodeAssistant(tools, ask=chat.ask_ui, on_event=chat.on_event)

    admin = AdminView()
    views = [chat, logs, admin]
    content = ft.Container(content=chat, expand=True, padding=0)

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=96,
        bgcolor=theme.CARD,
        indicator_color=theme.YELLOW,
        selected_label_text_style=ft.TextStyle(color=theme.RED_DARK,
                                               weight=ft.FontWeight.W_500),
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.CHAT_OUTLINED,
                                         selected_icon=ft.Icons.CHAT, label="Чат"),
            ft.NavigationRailDestination(icon=ft.Icons.HISTORY_OUTLINED,
                                         selected_icon=ft.Icons.HISTORY, label="Журнал"),
            ft.NavigationRailDestination(icon=ft.Icons.SETTINGS_OUTLINED,
                                         selected_icon=ft.Icons.SETTINGS, label="Админ"),
        ],
        on_change=lambda e: _swap(e.control.selected_index),
    )

    def _swap(index: int):
        content.content = views[index]
        page.update()  # контрол должен оказаться на странице до refresh()
        if index == 1:
            logs.refresh()
        elif index == 2:
            admin.refresh()

    page.add(ft.Column([
        _header(),
        ft.Row([rail, ft.VerticalDivider(width=1, color=theme.BORDER), content],
               expand=True, spacing=0),
    ], expand=True, spacing=0))

    if problems:  # некритичные (например, нет ключа) — баннер, не блокировка
        page.show_dialog(ft.SnackBar(
            ft.Text("Внимание: " + "; ".join(problems)),
            bgcolor=theme.RED_DARK, duration=15000))

    page.update()
