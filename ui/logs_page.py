"""Страница логов: статистика по диалогам/оценкам/токенам и журнал событий."""
from __future__ import annotations

import json

import flet as ft

from ui import app_context as ctx
from ui import theme as T

FILTERS = [("", "Все события"), ("dialog", "Диалоги"), ("rag", "RAG"),
           ("mcp", "MCP-вызовы"), ("llm", "LLM"), ("feedback", "Оценки"),
           ("system", "Система")]


class LogsPage:
    def __init__(self, page: ft.Page):
        self.page = page
        self.prefix = ""
        self.confirm_clear = False

    def build(self) -> ft.Control:
        self.root = ft.Column(expand=True, spacing=14,
                              scroll=ft.ScrollMode.AUTO)
        self._render()
        return self.root

    # ------------------------------------------------------------------

    def _stat_card(self, title: str, value: str, color: str) -> ft.Control:
        return T.card(ft.Column([
            ft.Text(title, size=12, color=T.GRAY_TEXT),
            ft.Text(value, size=24, weight=ft.FontWeight.W_600, color=color),
        ], spacing=2), padding=14, width=210)

    def _stats_row(self) -> ft.Control:
        logs = ctx.store.read_jsonl("logs.jsonl")
        tokens = sum((r.get("usage") or {}).get("total_tokens", 0)
                     for r in logs if r.get("event") == "llm.answer")
        avg = ctx.feedback.average_rating()
        return ft.Row([
            self._stat_card("Диалогов", str(ctx.dialogs.count()), T.ORANGE),
            self._stat_card("Оценок", str(ctx.feedback.count()), T.GREEN),
            self._stat_card("Средняя оценка",
                            f"{avg:.2f}" if avg is not None else "—",
                            T.GREEN),
            self._stat_card("Токены LLM (всего)", str(tokens), T.BLUE_GRAY),
            self._stat_card("Событий в журнале", str(len(logs)),
                            T.GRAY_TEXT),
        ], spacing=12, wrap=True)

    def _event_tile(self, rec: dict) -> ft.Control:
        event = rec.get("event", "")
        prefix = event.split(".")[0]
        payload = {k: v for k, v in rec.items()
                   if k not in ("id", "ts", "event")}
        return ft.ExpansionTile(
            title=ft.Row([
                ft.Text(rec.get("ts", ""), size=11, color=T.GRAY_TEXT,
                        width=170),
                T.event_chip(prefix),
                ft.Text(event, size=13, weight=ft.FontWeight.W_600,
                        color=T.INK),
            ], spacing=10),
            subtitle=ft.Text(str(payload)[:120], size=11,
                             color=T.GRAY_TEXT, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS),
            collapsed_bgcolor=T.GRAY_CARD,
            bgcolor=T.GRAY_CARD,
            controls_padding=T.pad_symmetric(10, 4),
            tile_padding=T.pad_symmetric(12, 2),
            controls=[
                ft.Container(
                    content=ft.Text(
                        json.dumps(payload, ensure_ascii=False, indent=2,
                                   default=str),
                        size=11, selectable=True, color=T.INK),
                    bgcolor=T.GRAY_BG, border=T.border_all(),
                    border_radius=8, padding=10,
                    margin=ft.Margin(0, 0, 0, 8)),
            ],
        )

    def _render(self) -> None:
        filter_dd = ft.Dropdown(
            label="Тип событий", value=self.prefix, width=220,
            options=[ft.DropdownOption(key=k, text=v)
                     for k, v in FILTERS],
            on_select=self.on_filter,
            border_color=T.GRAY_BORDER, focused_border_color=T.ORANGE,
            dense=True)

        if self.confirm_clear:
            clear_btn: ft.Control = ft.Row([
                ft.Text("Очистить журнал?", size=13, color=T.RED),
                ft.TextButton(content=ft.Text("Да"), on_click=self.on_clear_yes),
                ft.TextButton(content=ft.Text("Нет"), on_click=self.on_clear_no),
            ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        else:
            clear_btn = ft.TextButton(
                content=ft.Text("Очистить журнал", color=T.RED),
                icon=ft.Icons.DELETE, on_click=self.on_clear_request)

        header = ft.Row([
            ft.Text("Логи", size=22, weight=ft.FontWeight.W_600,
                    color=T.INK),
            filter_dd,
            ft.FilledButton(content=ft.Text("Обновить"),
                            icon=ft.Icons.REFRESH, bgcolor=T.ORANGE,
                            color=ft.Colors.WHITE, height=38,
                            on_click=self.on_refresh),
            clear_btn,
        ], spacing=12, wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER)

        records = ctx.log_repo.list(limit=300,
                                    prefix=self.prefix or None)
        tiles = [self._event_tile(r) for r in records]
        if not tiles:
            tiles = [ft.Text("Событий пока нет.", size=13,
                             color=T.GRAY_TEXT)]
        journal = T.card(ft.Column(tiles, spacing=2), padding=8)

        self.root.controls = [self._stats_row(), header, journal]

    # ------------------------------------------------------------------

    def on_filter(self, e) -> None:
        self.prefix = e.control.value or ""
        self._render()
        self.page.update()

    def on_refresh(self, e) -> None:
        self._render()
        self.page.update()

    def on_clear_request(self, e) -> None:
        self.confirm_clear = True
        self._render()
        self.page.update()

    def on_clear_no(self, e) -> None:
        self.confirm_clear = False
        self._render()
        self.page.update()

    def on_clear_yes(self, e) -> None:
        ctx.log_repo.clear()
        self.confirm_clear = False
        self._render()
        self.page.update()
