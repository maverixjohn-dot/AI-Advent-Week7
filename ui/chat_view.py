"""Чат с ассистентом: свободные вопросы и slash-команды."""
from __future__ import annotations

import logging

import flet as ft

from agent.assistant import Assistant
from ui import theme

log = logging.getLogger(__name__)

# /reindex намеренно не в чипах: длительная операция, запуск вручную из админки
# или командой, набранной текстом
QUICK_COMMANDS = ["/help", "/tree", "/objects", "/branch", "/diff"]


def _bubble(text: str, is_user: bool) -> ft.Control:
    body = ft.Text(text, selectable=True, color=ft.Colors.WHITE, size=14) if is_user else \
        ft.Markdown(text, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)
    return ft.Row(
        [ft.Container(
            content=body,
            bgcolor=theme.ORANGE if is_user else theme.CARD,
            border=None if is_user else theme.border_all(theme.BORDER),
            border_radius=14,
            padding=theme.pad_sym(14, 12),
            width=760,
            shadow=None if is_user else ft.BoxShadow(
                blur_radius=6, color="#0A00000014", offset=ft.Offset(0, 2)),
        )],
        alignment=ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START,
    )


class ChatView(ft.Column):
    def __init__(self, assistant: Assistant):
        super().__init__(expand=True, spacing=0)
        self.assistant = assistant

        self.messages = ft.ListView(expand=True, spacing=10, auto_scroll=True,
                                    padding=theme.pad_sym(16, 8))
        self.input = ft.TextField(
            hint_text="Вопрос о проекте или /команда…",
            expand=True, border_radius=10, filled=True, bgcolor=theme.CARD,
            border_color=theme.BORDER, focused_border_color=theme.ORANGE,
            on_submit=self._on_send,
        )
        send_btn = ft.IconButton(icon=ft.Icons.SEND, icon_color=ft.Colors.WHITE,
                                 bgcolor=theme.ORANGE, on_click=self._on_send,
                                 tooltip="Отправить")
        chips = ft.Row(
            [ft.TextButton(cmd, on_click=self._on_chip, data=cmd,
                           style=ft.ButtonStyle(color=theme.ORANGE_DARK))
             for cmd in QUICK_COMMANDS],
            spacing=0,
        )
        self.controls = [
            ft.Container(self.messages, expand=True),
            ft.Container(chips, padding=theme.pad_sym(16, 0)),
            ft.Container(ft.Row([self.input, send_btn], spacing=8),
                         padding=theme.pad_all(12), bgcolor=theme.BG),
        ]
        self._add_assistant("Ассистент разработчика 1С «Целеполагание».\n\n"
                            "Спросите о структуре конфигурации, коде или состоянии репозитория — "
                            "или начните со /help.")

    # --- вывод ---
    def _add_assistant(self, text: str):
        self.messages.controls.append(_bubble(text, is_user=False))

    def _add_user(self, text: str):
        self.messages.controls.append(_bubble(text, is_user=True))

    # --- события ---
    def _on_chip(self, e: ft.ControlEvent):
        # flet 1.x: у TextButton нет .text (первый аргумент — content),
        # команда хранится в data
        cmd = e.control.data
        self.input.value = cmd + (" " if cmd in ("/object", "/objects", "/diff") else "")
        self.input.focus()
        self.update()
        if cmd in ("/help", "/tree", "/branch", "/diff", "/reindex") and cmd not in ("/object", "/objects"):
            self.page.run_task(self._process, cmd)

    async def _on_send(self, e: ft.ControlEvent):
        await self._process(self.input.value)

    async def _process(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        self.input.value = ""
        self._add_user(text)
        typing = ft.Row([ft.Container(
            ft.Row([ft.ProgressRing(width=16, height=16, color=theme.ORANGE),
                    ft.Text("Думаю…", color=theme.TEXT_DIM)], spacing=8),
            padding=12)], alignment=ft.MainAxisAlignment.START)
        self.messages.controls.append(typing)
        self.update()

        try:
            answer = await (self.assistant.slash(text) if text.startswith("/")
                            else self.assistant.ask(text))
        except Exception as ex:
            log.exception("Ошибка обработки сообщения")
            answer = f"Ошибка: {ex}"
        self.messages.controls.remove(typing)
        self._add_assistant(answer)
        self.update()
