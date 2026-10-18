"""Чат аналитика с разработчиком (код-ассистентом 1С).

Ассистент работает в фоновом потоке (синхронное ядро); подтверждения
перезаписи и вопросы аналитику маршаллятся в UI-поток как модальные
диалоги: asyncio.run_coroutine_threadsafe(...).result() блокирует
рабочий поток до решения человека — семантика «советоваться перед
опасными действиями» сохраняется и в UI.
"""
from __future__ import annotations

import asyncio
import logging

import flet as ft

from agent.fs_tools import decode_1c_name
from ui import theme

log = logging.getLogger(__name__)

QUICK_TASKS = [
    "Найди, где используется объект",
    "Задокументируй объект в docs/",
    "Обнови документацию по изменениям",
    "Покажи diff предлагаемых правок",
]

TOOL_ICONS = {
    "list_files": ft.Icons.FOLDER_OPEN,
    "read_file": ft.Icons.DESCRIPTION_OUTLINED,
    "search_files": ft.Icons.SEARCH,
    "write_file": ft.Icons.EDIT_OUTLINED,
    "append_to_file": ft.Icons.POST_ADD,
    "ask_analyst": ft.Icons.QUESTION_ANSWER_OUTLINED,
}


def _bubble(text: str, is_user: bool) -> ft.Control:
    body = ft.Text(text, selectable=True, color=theme.TEXT, size=14) if is_user else \
        ft.Markdown(text, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)
    return ft.Row(
        [ft.Container(
            content=body,
            bgcolor=theme.YELLOW_SOFT if is_user else theme.CARD,
            border=theme.border_all(theme.YELLOW_EDGE if is_user else theme.BORDER),
            border_radius=14,
            padding=theme.pad_sym(14, 12),
            width=780,
            shadow=None if is_user else ft.BoxShadow(
                blur_radius=6, color="#0A00000012", offset=ft.Offset(0, 2)),
        )],
        alignment=ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START,
    )


class ChatView(ft.Column):
    def __init__(self, on_task_done=None):
        super().__init__(expand=True, spacing=0)
        self.assistant = None          # назначает app.py после создания
        self._on_task_done = on_task_done or (lambda: None)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._busy = False
        self._mounted = False
        self._build()

    # --- монтирование: события прогресса приходят из фонового потока и могут
    # попасть на момент, когда вкладка не на странице; update() там падает ---
    def did_mount(self):
        self._mounted = True

    def will_unmount(self):
        self._mounted = False

    def _safe_update(self):
        if not self._mounted:
            return
        try:
            self.update()
        except RuntimeError:  # вкладку переключили между проверкой и update
            pass

    def _build(self) -> None:
        self.messages = ft.ListView(expand=True, spacing=10, auto_scroll=True,
                                    padding=theme.pad_sym(16, 8))
        self._progress_steps = ft.Column(spacing=4, tight=True)
        self._progress_card = ft.Row([ft.Container(
            ft.Column([
                ft.Row([ft.ProgressRing(width=16, height=16, color=theme.RED),
                        ft.Text("Разработчик работает…", color=theme.TEXT_DIM)],
                       spacing=8),
                self._progress_steps,
            ], spacing=8, tight=True),
            bgcolor=theme.CARD, border=theme.border_all(theme.BORDER),
            border_radius=14, padding=theme.pad_sym(14, 12), width=780)],
            alignment=ft.MainAxisAlignment.START)

        self.input = ft.TextField(
            hint_text="Задача для разработчика: что доработать или задокументировать…",
            expand=True, border_radius=10, filled=True, bgcolor=theme.CARD,
            border_color=theme.BORDER, focused_border_color=theme.RED,
            on_submit=self._on_send,
        )
        self.send_btn = ft.IconButton(icon=ft.Icons.SEND, icon_color=ft.Colors.WHITE,
                                      bgcolor=theme.RED, on_click=self._on_send,
                                      tooltip="Поставить задачу")
        chips = ft.Row(
            [ft.TextButton(t, on_click=self._on_chip, data=t,
                           style=ft.ButtonStyle(color=theme.RED_DARK))
             for t in QUICK_TASKS],
            spacing=0, wrap=True,
        )
        self.controls = [
            ft.Container(self.messages, expand=True),
            ft.Container(chips, padding=theme.pad_sym(16, 0)),
            ft.Container(ft.Row([self.input, self.send_btn], spacing=8),
                         padding=theme.pad_all(12), bgcolor=theme.BG),
        ]
        self._add_assistant(
            "Код-ассистент 1С — эксперт-разработчик. Поставьте задачу на уровне цели: "
            "например, «найди, где используется Справочник.ФинансовыеПоказатели» или "
            "«задокументируй документ ФинансовыйФакт в docs/».\n\n"
            "Перезапись существующих файлов выполняется только после вашего "
            "подтверждения — диалог появится автоматически.")

    # ---------------------------------------------------------------- вывод
    def _add_assistant(self, text: str):
        self.messages.controls.append(_bubble(text, is_user=False))

    def _add_user(self, text: str):
        self.messages.controls.append(_bubble(text, is_user=True))

    # ------------------------------------------------- колбэки для ассистента
    # Вызываются из рабочего потока run_task; run_coroutine_threadsafe().result()
    # блокирует поток до ответа UI.

    def confirm_ui(self, action: str, diff: str) -> bool:
        """Подтверждение опасного действия диалогом (worker thread -> bool)."""
        if self._loop is None:
            return False
        fut = asyncio.run_coroutine_threadsafe(
            self._confirm_async(action, diff), self._loop)
        try:
            return bool(fut.result())
        except Exception:
            log.exception("Диалог подтверждения упал — считаем отказом")
            return False

    def ask_ui(self, question: str) -> str:
        """Вопрос ассистента аналитику (worker thread -> str)."""
        if self._loop is None:
            return "(UI недоступен — аналитик не ответил)"
        fut = asyncio.run_coroutine_threadsafe(self._ask_async(question), self._loop)
        try:
            return fut.result()
        except Exception:
            log.exception("Диалог вопроса упал")
            return "(аналитик не ответил)"

    def on_event(self, kind: str, payload: dict):
        """Прогресс агентского цикла (worker thread, fire-and-forget)."""
        if self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._progress_async(kind, payload), self._loop)
        except RuntimeError:
            pass

    # ---------------------------------------------------------- UI-поток
    async def _confirm_async(self, action: str, diff: str) -> bool:
        loop = asyncio.get_running_loop()
        result: asyncio.Future = loop.create_future()

        def _close(value: bool):
            if not result.done():
                result.set_result(value)
            try:
                self.page.pop_dialog()
            except Exception:
                dlg.open = False
                self.page.update()

        diff_view = ft.Container(
            ft.Column([ft.Text(diff or "(нет diff)", font_family="monospace",
                               size=11, color=theme.MONO_FG, selectable=True)],
                      scroll=ft.ScrollMode.AUTO, tight=True),
            bgcolor=theme.MONO_BG, border_radius=8, padding=10,
            width=720, height=320,
        )
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=theme.RED),
                          ft.Text("Требуется подтверждение", weight=ft.FontWeight.BOLD)],
                         spacing=8),
            content=ft.Column([
                ft.Text(action, color=theme.TEXT, weight=ft.FontWeight.W_500),
                diff_view,
            ], spacing=10, tight=True, width=760),
            actions=[
                ft.TextButton("Отклонить",
                              style=ft.ButtonStyle(color=theme.TEXT_DIM),
                              on_click=lambda e: _close(False)),
                ft.Button("Подтвердить", bgcolor=theme.RED, color=ft.Colors.WHITE,
                          on_click=lambda e: _close(True)),
            ],
        )
        self.page.show_dialog(dlg)
        return await result

    async def _ask_async(self, question: str) -> str:
        loop = asyncio.get_running_loop()
        result: asyncio.Future = loop.create_future()
        field = ft.TextField(label="Ваш ответ", autofocus=True, multiline=True,
                             min_lines=2, max_lines=5, expand=True,
                             border_color=theme.BORDER, focused_border_color=theme.RED)

        def _send(e=None):
            if not result.done():
                result.set_result(field.value.strip() or "(аналитик не ответил)")
            try:
                self.page.pop_dialog()
            except Exception:
                dlg.open = False
                self.page.update()

        field.on_submit = _send
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.QUESTION_ANSWER, color=theme.RED),
                          ft.Text("Разработчик спрашивает", weight=ft.FontWeight.BOLD)],
                         spacing=8),
            content=ft.Column([ft.Text(question, selectable=True, color=theme.TEXT),
                               field], spacing=10, tight=True, width=640),
            actions=[ft.Button("Ответить", bgcolor=theme.RED, color=ft.Colors.WHITE,
                               on_click=_send)],
        )
        self.page.show_dialog(dlg)
        return await result

    async def _progress_async(self, kind: str, payload: dict):
        if kind == "tool_call":
            name = payload.get("name", "?")
            args = payload.get("args", {})
            hint = ""
            for key in ("path", "query", "subdir", "question"):
                if key in args:
                    hint = str(args[key])
                    break
            icon = TOOL_ICONS.get(name, ft.Icons.BUILD_OUTLINED)
            shown_hint = decode_1c_name(hint) if hint else ""
            self._progress_steps.controls.append(
                ft.Row([ft.Icon(icon, size=14, color=theme.RED_DARK),
                        ft.Text(f"{name}  {shown_hint[:110]}", size=12,
                                color=theme.TEXT_DIM, selectable=True)],
                       spacing=6))
        elif kind == "tool_result":
            preview = (payload.get("preview") or "").strip().splitlines()
            first = preview[0][:110] if preview else ""
            if first.startswith("ОТКАЗ"):
                self._progress_steps.controls.append(
                    ft.Row([ft.Icon(ft.Icons.BLOCK, size=14, color=theme.RED),
                            ft.Text(first, size=12, color=theme.RED, selectable=True)],
                           spacing=6))
        if self._progress_card in self.messages.controls:
            self._safe_update()

    # ------------------------------------------------------------- события
    def _on_chip(self, e: ft.ControlEvent):
        self.input.value = e.control.data
        self.input.focus()
        self._safe_update()

    async def _on_send(self, e: ft.ControlEvent):
        text = (self.input.value or "").strip()
        if not text or self._busy:
            return
        self._loop = asyncio.get_running_loop()
        self.input.value = ""
        self._add_user(text)
        self._progress_steps.controls.clear()
        self.messages.controls.append(self._progress_card)
        self._set_busy(True)

        try:
            answer = await asyncio.to_thread(self.assistant.run_task, text)
        except Exception as ex:
            log.exception("Ошибка выполнения задачи")
            answer = f"Ошибка: {ex}"
        if self._progress_card in self.messages.controls:
            self.messages.controls.remove(self._progress_card)
        self._add_assistant(answer)
        self._set_busy(False)
        self._on_task_done()

    def _set_busy(self, busy: bool):
        self._busy = busy
        self.send_btn.disabled = busy
        self.input.disabled = busy
        self._safe_update()
