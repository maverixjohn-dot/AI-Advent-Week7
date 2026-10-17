"""Пользовательская страница: идентификация → чат с ассистентом →
форма оценки качества поддержки после завершения диалога."""
from __future__ import annotations

import asyncio

import flet as ft

from ui import app_context as ctx
from ui import theme as T


class UserPage:
    def __init__(self, page: ft.Page):
        self.page = page
        self.mode = "ident"          # ident | chat | feedback | thanks
        self.dialog_id: str | None = None
        self.context: dict | None = None
        self.rating = 0
        self.busy = False
        self.error = ""
        self.confirm_close = False

    # ------------------------------------------------------------------

    def build(self) -> ft.Control:
        self.root = ft.Column(expand=True, spacing=16)
        self._render()
        return self.root

    def _render(self) -> None:
        if self.mode == "chat":
            self._render_chat()
        elif self.mode == "feedback":
            self._render_feedback()
        elif self.mode == "thanks":
            self._render_thanks()
        else:
            self._render_ident()

    def _refresh(self) -> None:
        self._render()
        self.page.update()

    # ------------------------------------------------------------------
    # 1. Идентификация
    # ------------------------------------------------------------------

    def _render_ident(self) -> None:
        self.ident_field = ft.TextField(
            label="Email или номер тикета",
            hint_text="ivan.petrov@example.com или T-1001",
            width=420, autofocus=True, on_submit=self.on_start,
            border_color=T.GRAY_BORDER, focused_border_color=T.ORANGE,
            cursor_color=T.ORANGE, disabled=self.busy)
        start_btn = ft.FilledButton(
            content=ft.Text("Начать диалог", size=15),
            icon=ft.Icons.CHAT, bgcolor=T.ORANGE, color=ft.Colors.WHITE,
            height=48, width=220, on_click=self.on_start, disabled=self.busy)
        error_text = ft.Text(self.error, color=T.RED, size=13,
                             visible=bool(self.error))

        form = T.card(ft.Column([
            ft.Row([ft.Icon(ft.Icons.SUPPORT_AGENT, color=T.ORANGE, size=30),
                    ft.Text("Поддержка «Контур.Учёт»", size=22,
                            weight=ft.FontWeight.W_600, color=T.INK)],
                   spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Text("Введите email учётной записи или номер тикета — "
                    "ассистент подхватит контекст обращения.",
                    size=13, color=T.GRAY_TEXT),
            ft.Container(height=6),
            self.ident_field,
            ft.Row([start_btn,
                    ft.ProgressRing(width=22, height=22, stroke_width=2,
                                    color=T.ORANGE, visible=self.busy)],
                   spacing=12,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            error_text,
        ], spacing=10), padding=24, width=560)

        demo = T.card(ft.Column([
            T.section_title("Демо-доступ", ft.Icons.PERSON),
            ft.Text("ivan.petrov@example.com — тикет T-1001 про ошибку "
                    "авторизации AUTH-403", size=12, color=T.GRAY_TEXT),
            ft.Text("maria.s@example.com — тикеты T-1002, T-1008",
                    size=12, color=T.GRAY_TEXT),
            ft.Text("oleg.gromov@example.com — тикеты T-1003, T-1007",
                    size=12, color=T.GRAY_TEXT),
        ], spacing=4), width=560)

        self.root.controls = [
            ft.Row([ft.Column([form, demo], spacing=16,
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER)],
                   alignment=ft.MainAxisAlignment.CENTER, expand=True),
        ]

    async def on_start(self, e) -> None:
        ident = (self.ident_field.value or "").strip()
        self.busy, self.error = True, ""
        self._refresh()
        try:
            dialog, context = await asyncio.to_thread(
                ctx.agent.start_dialog, ident)
            self.dialog_id, self.context = dialog.id, context
            self.mode = "chat"
        except Exception as ex:
            self.error = str(ex)
        self.busy = False
        self._refresh()

    # ------------------------------------------------------------------
    # 2. Чат
    # ------------------------------------------------------------------

    def _render_chat(self) -> None:
        sidebar = self._sidebar()

        self.chat_list = ft.ListView(expand=True, spacing=10,
                                     auto_scroll=True,
                                     padding=T.pad_symmetric(8, 12))
        dialog = ctx.dialogs.get(self.dialog_id) if self.dialog_id else None
        if dialog and dialog.messages:
            for m in dialog.messages:
                self.chat_list.controls.append(self._bubble(m))
        else:
            self.chat_list.controls.append(self._greeting())
        if self.busy:
            self.chat_list.controls.append(
                ft.Row([ft.Container(
                    content=ft.Row([ft.ProgressRing(width=16, height=16,
                                                    stroke_width=2,
                                                    color=T.ORANGE),
                                    ft.Text("Ассистент печатает…", size=12,
                                            color=T.GRAY_TEXT)], spacing=8),
                    bgcolor=T.GRAY_CARD, border=T.border_all(),
                    border_radius=14, padding=12)],
                    alignment=ft.MainAxisAlignment.START))

        self.input = ft.TextField(
            hint_text="Опишите проблему или задайте вопрос…",
            expand=True, on_submit=self.on_send, disabled=self.busy,
            border_color=T.GRAY_BORDER, focused_border_color=T.ORANGE,
            cursor_color=T.ORANGE, shift_enter=True)
        send_btn = ft.IconButton(
            ft.Icons.SEND, icon_color=ft.Colors.WHITE, bgcolor=T.ORANGE,
            on_click=self.on_send, disabled=self.busy, tooltip="Отправить")
        input_row = T.card(ft.Row([self.input, send_btn], spacing=8,
                                  vertical_alignment=ft.CrossAxisAlignment.CENTER),
                           padding=10)

        self.root.controls = [
            ft.Row([sidebar,
                    ft.Column([ft.Container(self.chat_list, expand=True),
                               input_row], expand=True, spacing=10)],
                   expand=True, spacing=16,
                   vertical_alignment=ft.CrossAxisAlignment.START),
        ]

    def _greeting(self) -> ft.Control:
        user = (self.context or {}).get("user") or {}
        ticket = (self.context or {}).get("ticket")
        text = f"Здравствуйте, {user.get('name', '')}!"
        if ticket:
            text += (f" Вижу ваш тикет {ticket.get('number')} "
                     f"«{ticket.get('subject')}» (статус: "
                     f"{ticket.get('status')}).")
        text += " Опишите проблему — отвечу с учётом базы знаний и вашего тикета."
        return ft.Row([ft.Container(
            content=ft.Text(text, size=14, color=T.INK, selectable=True),
            bgcolor=T.GRAY_CARD, border=T.left_accent(T.GREEN),
            border_radius=14, padding=14, width=640)],
            alignment=ft.MainAxisAlignment.START)

    def _bubble(self, m: dict) -> ft.Control:
        is_user = m["role"] == "user"
        if is_user:
            box = ft.Container(
                content=ft.Text(m["content"], size=14, color=T.INK,
                                selectable=True),
                bgcolor=T.ORANGE_SOFT, border=T.border_all(1, T.ORANGE_BORDER),
                border_radius=14, padding=14, width=640)
            return ft.Row([box], alignment=ft.MainAxisAlignment.END)

        extras: list[ft.Control] = []
        sources = m.get("sources") or []
        if sources:
            extras.append(ft.Row(wrap=True, spacing=6, controls=[
                ft.Container(
                    content=ft.Text(f"{s['doc']} · {s['score']}", size=11,
                                    color=T.GREEN),
                    bgcolor=T.GREEN_SOFT, border_radius=10,
                    padding=T.pad_symmetric(8, 2))
                for s in sources]))
        meta_bits = []
        if m.get("tool_calls"):
            meta_bits.append("инструменты: " + ", ".join(m["tool_calls"]))
        usage = m.get("usage") or {}
        if usage.get("total_tokens"):
            meta_bits.append(f"токены: {usage['total_tokens']}")
        if meta_bits:
            extras.append(ft.Text(" · ".join(meta_bits), size=10,
                                  color=T.GRAY_TEXT))
        box = ft.Container(
            content=ft.Column(
                [ft.Markdown(m["content"], selectable=True)] + extras,
                spacing=8),
            bgcolor=T.GRAY_CARD, border=T.left_accent(T.GREEN),
            border_radius=14, padding=14, width=640)
        return ft.Row([box], alignment=ft.MainAxisAlignment.START)

    def _sidebar(self) -> ft.Control:
        user = (self.context or {}).get("user") or {}
        ticket = (self.context or {}).get("ticket")

        def kv(k: str, v: str) -> ft.Row:
            return ft.Row([ft.Text(k, size=12, color=T.GRAY_TEXT, width=90),
                           ft.Text(v or "—", size=12, color=T.INK,
                                   selectable=True, expand=True)],
                          spacing=6,
                          vertical_alignment=ft.CrossAxisAlignment.START)

        user_card = T.card(ft.Column([
            T.section_title("Пользователь", ft.Icons.PERSON),
            kv("Имя", user.get("name", "")),
            kv("Email", user.get("email", "")),
            kv("Компания", user.get("company", "")),
            kv("Тариф", user.get("plan", "")),
            kv("Версия", user.get("product_version", "")),
        ], spacing=6), width=300)

        if ticket:
            ticket_card = T.card(ft.Column([
                T.section_title(f"Тикет {ticket.get('number', '')}",
                                ft.Icons.BUG_REPORT),
                ft.Row([T.status_chip(ticket.get("status", "")),
                        ft.Text(ticket.get("priority", ""), size=12,
                                color=T.GRAY_TEXT)], spacing=8),
                ft.Text(ticket.get("subject", ""), size=13,
                        weight=ft.FontWeight.W_600, color=T.INK),
                kv("Раздел", ticket.get("product_area", "")),
                kv("Окружение", ticket.get("environment", "")),
            ], spacing=6), width=300)
        else:
            ticket_card = T.card(ft.Column([
                T.section_title("Тикет", ft.Icons.BUG_REPORT),
                ft.Text("Активный тикет не найден. Ответы будут опираться "
                        "только на базу знаний.", size=12,
                        color=T.GRAY_TEXT),
            ], spacing=6), width=300)

        if self.confirm_close:
            close_block: ft.Control = T.card(ft.Column([
                ft.Text("Завершить диалог и перейти к оценке поддержки?",
                        size=13, color=T.INK),
                ft.Row([
                    ft.FilledButton(content=ft.Text("Да"), bgcolor=T.GREEN,
                                    color=ft.Colors.WHITE,
                                    on_click=self.on_close_yes),
                    ft.TextButton(content=ft.Text("Нет"),
                                  on_click=self.on_close_no),
                ], spacing=8),
            ], spacing=8), width=300)
        else:
            close_block = ft.Container(
                content=ft.OutlinedButton(
                    content=ft.Text("Завершить диалог", size=14),
                    icon=ft.Icons.CLOSE, width=260, height=44,
                    on_click=self.on_close_request,
                    style=ft.ButtonStyle(color=T.ORANGE_DARK,
                                         side={ft.ControlState.DEFAULT:
                                               ft.BorderSide(1, T.ORANGE)})),
                width=300, alignment=T.ALIGN_CENTER)

        return ft.Column([user_card, ticket_card, close_block], spacing=12,
                         width=300)

    async def on_send(self, e) -> None:
        text = (self.input.value or "").strip()
        if not text or not self.dialog_id:
            return
        self.busy = True
        self._refresh()
        try:
            await asyncio.to_thread(ctx.agent.ask, self.dialog_id, text)
        except Exception as ex:
            ctx.log_service.log("dialog.error", dialog_id=self.dialog_id,
                                error=str(ex))
            # показываем ошибку как сообщение в чате, не ломая диалог
            dialog = ctx.dialogs.get(self.dialog_id)
            if dialog is not None:
                from data.models import new_message
                dialog.messages.append(new_message(
                    "assistant",
                    f"**Ошибка:** {ex}\n\nПроверьте, что задан ключ "
                    "DEEPSEEK_API_KEY и доступен MCP-сервер."))
        self.busy = False
        self._refresh()

    def on_close_request(self, e) -> None:
        self.confirm_close = True
        self._refresh()

    def on_close_no(self, e) -> None:
        self.confirm_close = False
        self._refresh()

    async def on_close_yes(self, e) -> None:
        self.confirm_close = False
        if self.dialog_id:
            await asyncio.to_thread(ctx.agent.close_dialog, self.dialog_id)
        self.mode = "feedback"
        self._refresh()

    # ------------------------------------------------------------------
    # 3. Форма оценки
    # ------------------------------------------------------------------

    def _render_feedback(self) -> None:
        stars = ft.Row([
            ft.IconButton(
                ft.Icons.STAR if i < self.rating else ft.Icons.STAR_BORDER,
                icon_color=T.ORANGE, icon_size=40,
                on_click=lambda e, i=i: self._set_rating(i + 1),
                tooltip=f"{i + 1} из 5")
            for i in range(5)], spacing=4,
            alignment=ft.MainAxisAlignment.CENTER)
        self.comment_field = ft.TextField(
            label="Комментарий (необязательно)", multiline=True,
            min_lines=3, max_lines=5, width=460,
            border_color=T.GRAY_BORDER, focused_border_color=T.ORANGE,
            cursor_color=T.ORANGE)
        self.feedback_error = ft.Text("", color=T.RED, size=13,
                                      visible=False)

        form = T.card(ft.Column([
            ft.Row([ft.Icon(ft.Icons.STAR_RATE, color=T.ORANGE, size=30),
                    ft.Text("Оцените качество поддержки", size=20,
                            weight=ft.FontWeight.W_600, color=T.INK)],
                   spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Text("Диалог завершён. Ваша оценка поможет улучшить "
                    "работу ассистента.", size=13, color=T.GRAY_TEXT),
            stars,
            self.comment_field,
            ft.Row([
                ft.FilledButton(content=ft.Text("Отправить оценку",
                                                size=15),
                                icon=ft.Icons.CHECK_CIRCLE, bgcolor=T.GREEN,
                                color=ft.Colors.WHITE, height=46, width=240,
                                on_click=self.on_submit_feedback,
                                disabled=self.rating == 0 or self.busy),
                ft.ProgressRing(width=22, height=22, stroke_width=2,
                                color=T.GREEN, visible=self.busy),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.feedback_error,
        ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=28, width=560)

        self.root.controls = [
            ft.Row([form], alignment=ft.MainAxisAlignment.CENTER,
                   expand=True)]

    def _set_rating(self, value: int) -> None:
        self.rating = value
        self._refresh()

    async def on_submit_feedback(self, e) -> None:
        if self.rating == 0 or not self.dialog_id:
            return
        self.busy = True
        self._refresh()
        try:
            await asyncio.to_thread(
                ctx.agent.submit_feedback, self.dialog_id, self.rating,
                self.comment_field.value or "")
            self.mode = "thanks"
        except Exception as ex:
            self.feedback_error.value = str(ex)
            self.feedback_error.visible = True
        self.busy = False
        self._refresh()

    # ------------------------------------------------------------------
    # 4. Благодарность
    # ------------------------------------------------------------------

    def _render_thanks(self) -> None:
        self.root.controls = [
            ft.Row([T.card(ft.Column([
                ft.Icon(ft.Icons.CHECK_CIRCLE, color=T.GREEN, size=56),
                ft.Text("Спасибо за оценку!", size=20,
                        weight=ft.FontWeight.W_600, color=T.INK),
                ft.Text(f"Вы поставили {self.rating} из 5. Оценка и "
                        "комментарий сохранены и видны администратору.",
                        size=13, color=T.GRAY_TEXT,
                        text_align=ft.TextAlign.CENTER),
                ft.Container(height=6),
                ft.FilledButton(content=ft.Text("Начать новый диалог",
                                                size=15),
                                icon=ft.Icons.CHAT, bgcolor=T.ORANGE,
                                color=ft.Colors.WHITE, height=46, width=260,
                                on_click=self.on_new_dialog),
            ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=32, width=560)],
                alignment=ft.MainAxisAlignment.CENTER, expand=True),
        ]

    def on_new_dialog(self, e) -> None:
        self.mode = "ident"
        self.dialog_id = None
        self.context = None
        self.rating = 0
        self.error = ""
        self._refresh()
