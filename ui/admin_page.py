"""Страница администрирования: база знаний, данные CRM, настройки агента."""
from __future__ import annotations

import asyncio
from pathlib import Path

import flet as ft

from data.models import AVAILABLE_MODELS, REASONING_EFFORTS
from ui import app_context as ctx
from ui import theme as T

SECTIONS = [("kb", "База знаний"), ("crm", "CRM: пользователи и тикеты"),
            ("settings", "Настройки агента")]


class AdminPage:
    def __init__(self, page: ft.Page):
        self.page = page
        self.section = "kb"
        self.busy = False
        self.status_msg = ""
        self.status_ok = True
        # FilePicker — service-контрол Flet 1.x: добавляется в page.services,
        # в page.overlay его класть нельзя («Unknown control: FilePicker»)
        self.picker = ft.FilePicker()
        page.services.append(self.picker)

    # ------------------------------------------------------------------

    def build(self) -> ft.Control:
        self.root = ft.Column(expand=True, spacing=14,
                              scroll=ft.ScrollMode.AUTO)
        self._render()
        return self.root

    def _render(self) -> None:
        nav = ft.Row([
            ft.FilledButton(
                content=ft.Text(label), height=38,
                bgcolor=T.ORANGE if key == self.section else T.GRAY_CARD,
                color=ft.Colors.WHITE if key == self.section else T.INK,
                on_click=lambda e, k=key: self._switch(k))
            for key, label in SECTIONS], spacing=8)

        mcp_ok = False
        try:
            mcp_ok = ctx.mcp.ping()
        except Exception:
            mcp_ok = False
        mcp_chip = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CLOUD_DONE if mcp_ok
                        else ft.Icons.CLOUD_OFF,
                        color=ft.Colors.WHITE, size=16),
                ft.Text("MCP: подключён" if mcp_ok else "MCP: недоступен",
                        size=12, color=ft.Colors.WHITE)], spacing=6),
            bgcolor=T.GREEN if mcp_ok else T.RED, border_radius=10,
            padding=T.pad_symmetric(10, 6))

        status = ft.Text(self.status_msg,
                         color=T.GREEN if self.status_ok else T.RED,
                         size=13, visible=bool(self.status_msg))

        if self.section == "crm":
            content = self._crm_section()
        elif self.section == "settings":
            content = self._settings_section()
        else:
            content = self._kb_section()

        self.root.controls = [
            ft.Row([ft.Text("Администрирование", size=22,
                            weight=ft.FontWeight.W_600, color=T.INK),
                    mcp_chip], spacing=16,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            nav, status, content,
        ]

    def _switch(self, section: str) -> None:
        self.section = section
        self.status_msg = ""
        self._render()
        self.page.update()

    def _set_status(self, msg: str, ok: bool = True) -> None:
        self.status_msg, self.status_ok = msg, ok

    # ------------------------------------------------------------------
    # База знаний
    # ------------------------------------------------------------------

    def _kb_section(self) -> ft.Control:
        idx = ctx.index_status
        idx_color = {"ready": T.GREEN, "building": T.ORANGE,
                     "error": T.RED}.get(idx["state"], T.GRAY_TEXT)
        info = T.card(ft.Column([
            T.section_title("Индекс RAG", ft.Icons.STORAGE),
            ft.Row([
                ft.Text(f"Модель эмбеддингов: {ctx.DEFAULT_MODEL} (CPU)",
                        size=13, color=T.GRAY_TEXT),
                ft.Container(
                    content=ft.Text(f"{idx['state']}: {idx['detail']}",
                                    size=12, color=ft.Colors.WHITE),
                    bgcolor=idx_color, border_radius=10,
                    padding=T.pad_symmetric(8, 4)),
                ft.Text(f"Чанков в индексе: {ctx.vector_store.count()}",
                        size=13, color=T.GRAY_TEXT),
            ], spacing=14, wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([
                ft.FilledButton(content=ft.Text("Переиндексировать всё"),
                                icon=ft.Icons.REFRESH, bgcolor=T.ORANGE,
                                color=ft.Colors.WHITE, height=40,
                                on_click=self.on_reindex,
                                disabled=self.busy),
                ft.OutlinedButton(content=ft.Text("Загрузить .md / .txt"),
                                  icon=ft.Icons.UPLOAD_FILE, height=40,
                                  on_click=self.on_pick,
                                  disabled=self.busy,
                                  style=ft.ButtonStyle(color=T.ORANGE_DARK)),
                ft.ProgressRing(width=22, height=22, stroke_width=2,
                                color=T.ORANGE, visible=self.busy),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=10))

        self.doc_name = ft.TextField(
            label="Имя документа", hint_text="например, faq-delivery.md",
            width=380, border_color=T.GRAY_BORDER,
            focused_border_color=T.ORANGE, cursor_color=T.ORANGE)
        self.doc_content = ft.TextField(
            label="Текст документа (Markdown)", multiline=True,
            min_lines=6, max_lines=12, expand=True,
            border_color=T.GRAY_BORDER, focused_border_color=T.ORANGE,
            cursor_color=T.ORANGE)
        paste = T.card(ft.Column([
            T.section_title("Добавить документ текстом", ft.Icons.ARTICLE),
            self.doc_name, self.doc_content,
            ft.FilledButton(content=ft.Text("Сохранить и проиндексировать"),
                            icon=ft.Icons.CHECK_CIRCLE, bgcolor=T.GREEN,
                            color=ft.Colors.WHITE, height=40,
                            on_click=self.on_add_doc, disabled=self.busy),
        ], spacing=10))

        docs = ctx.kb_repo.list()
        rows = []
        for d in docs:
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(d.name, size=13)),
                ft.DataCell(ft.Text(d.filename, size=12,
                                    color=T.GRAY_TEXT)),
                ft.DataCell(ft.Text(str(d.chunk_count), size=13)),
                ft.DataCell(ft.Text(d.status, size=12,
                                    color=T.GREEN if d.status == "indexed"
                                    else T.RED)),
                ft.DataCell(ft.Text(d.uploaded_at, size=12,
                                    color=T.GRAY_TEXT)),
                ft.DataCell(ft.IconButton(
                    ft.Icons.DELETE, icon_color=T.RED, icon_size=18,
                    tooltip="Удалить документ",
                    on_click=lambda e, fn=d.filename: self.page.run_task(
                        self.on_delete_doc, fn))),
            ]))
        table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text("Документ")),
                     ft.DataColumn(ft.Text("Файл")),
                     ft.DataColumn(ft.Text("Чанков"), numeric=True),
                     ft.DataColumn(ft.Text("Статус")),
                     ft.DataColumn(ft.Text("Загружен")),
                     ft.DataColumn(ft.Text(""))],
            rows=rows, column_spacing=24, border=T.border_all(),
            heading_row_color=T.GRAY_BG)
        docs_card = T.card(ft.Column([
            T.section_title(f"Документы ({len(docs)})", ft.Icons.LIST_ALT),
            ft.Row([table], scroll=ft.ScrollMode.AUTO),
        ], spacing=10))
        return ft.Column([info, paste, docs_card], spacing=14)

    async def on_reindex(self, e) -> None:
        self.busy = True
        self._set_status("Индексация… (при первом запуске модель ~2,2 ГБ "
                         "может скачиваться несколько минут)")
        self._render()
        self.page.update()
        await asyncio.to_thread(ctx.ensure_index, True)
        idx = ctx.index_status
        self.busy = False
        if idx["state"] == "ready":
            self._set_status(f"Индекс перестроен: {idx['detail']}")
        else:
            self._set_status(f"Ошибка индексации: {idx['detail']}", ok=False)
        self._render()
        self.page.update()

    async def on_pick(self, e) -> None:
        try:
            files = await self.picker.pick_files(
                dialog_title="Документ базы знаний",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["md", "txt"], with_data=True)
        except Exception as ex:
            self._set_status(f"Выбор файла не удался: {ex}", ok=False)
            self._render()
            self.page.update()
            return
        added = []
        for f in files or []:
            data = f.bytes
            if data is None and getattr(f, "path", None):
                data = Path(f.path).read_bytes()
            if not data:
                continue
            self.busy = True
            self._render()
            self.page.update()
            try:
                doc = await asyncio.to_thread(
                    ctx.knowledge.add_text_document, f.name,
                    data.decode("utf-8", "replace"))
                added.append(f"{doc.filename} ({doc.chunk_count} чанков)")
            except Exception as ex:
                self._set_status(f"Ошибка индексации {f.name}: {ex}",
                                 ok=False)
            self.busy = False
        if added:
            self._set_status("Добавлено: " + ", ".join(added))
        self._render()
        self.page.update()

    async def on_add_doc(self, e) -> None:
        name = (self.doc_name.value or "").strip()
        content = (self.doc_content.value or "").strip()
        if not name or not content:
            self._set_status("Заполните имя и текст документа", ok=False)
            self._render()
            self.page.update()
            return
        self.busy = True
        self._render()
        self.page.update()
        try:
            doc = await asyncio.to_thread(
                ctx.knowledge.add_text_document, name, content)
            self._set_status(f"Документ {doc.filename} проиндексирован: "
                             f"{doc.chunk_count} чанков")
        except Exception as ex:
            self._set_status(f"Ошибка: {ex}", ok=False)
        self.busy = False
        self._render()
        self.page.update()

    async def on_delete_doc(self, filename: str) -> None:
        self.busy = True
        self._render()
        self.page.update()
        try:
            await asyncio.to_thread(ctx.knowledge.delete_document, filename)
            self._set_status(f"Документ {filename} удалён, индекс перестроен")
        except Exception as ex:
            self._set_status(f"Ошибка удаления: {ex}", ok=False)
        self.busy = False
        self._render()
        self.page.update()

    # ------------------------------------------------------------------
    # CRM: пользователи и тикеты
    # ------------------------------------------------------------------

    def _crm_section(self) -> ft.Control:
        users = ctx.users.list()
        tickets = ctx.tickets.list()
        user_names = {u.id: u.name for u in users}

        # --- форма создания пользователя (через MCP-инструмент) ---
        tf = dict(border_color=T.GRAY_BORDER, focused_border_color=T.ORANGE,
                  cursor_color=T.ORANGE, dense=True)
        self.nu_name = ft.TextField(label="Имя *", width=240, **tf)
        self.nu_email = ft.TextField(label="Email *", width=240, **tf)
        self.nu_company = ft.TextField(label="Компания", width=200, **tf)
        self.nu_plan = ft.Dropdown(
            label="Тариф", value="basic", width=150, dense=True,
            options=[ft.DropdownOption(key=p, text=p)
                     for p in ("basic", "pro", "enterprise")],
            border_color=T.GRAY_BORDER, focused_border_color=T.ORANGE)
        self.nu_version = ft.TextField(label="Версия", width=120,
                                       hint_text="4.2.1", **tf)
        create_card = T.card(ft.Column([
            T.section_title("Новый пользователь", ft.Icons.PERSON_ADD),
            ft.Row([self.nu_name, self.nu_email, self.nu_company,
                    self.nu_plan, self.nu_version], spacing=10, wrap=True),
            ft.FilledButton(content=ft.Text("Создать пользователя"),
                            icon=ft.Icons.CHECK_CIRCLE, bgcolor=T.GREEN,
                            color=ft.Colors.WHITE, height=40,
                            on_click=self.on_create_user,
                            disabled=self.busy),
        ], spacing=10))

        user_rows = [ft.DataRow(cells=[
            ft.DataCell(ft.Text(u.name, size=13)),
            ft.DataCell(ft.Text(u.email, size=13)),
            ft.DataCell(ft.Text(u.company, size=12, color=T.GRAY_TEXT)),
            ft.DataCell(ft.Text(u.plan, size=13)),
            ft.DataCell(ft.Text(u.product_version, size=13)),
        ]) for u in users]
        users_table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text("Имя")),
                     ft.DataColumn(ft.Text("Email")),
                     ft.DataColumn(ft.Text("Компания")),
                     ft.DataColumn(ft.Text("Тариф")),
                     ft.DataColumn(ft.Text("Версия"))],
            rows=user_rows, column_spacing=24, border=T.border_all(),
            heading_row_color=T.GRAY_BG)

        ticket_rows = [ft.DataRow(cells=[
            ft.DataCell(ft.Text(t.number, size=13,
                                weight=ft.FontWeight.W_600)),
            ft.DataCell(ft.Text(user_names.get(t.user_id, t.user_id),
                                size=12)),
            ft.DataCell(ft.Text(t.subject, size=12)),
            ft.DataCell(T.status_chip(t.status)),
            ft.DataCell(ft.Text(t.priority, size=12)),
            ft.DataCell(ft.Text(t.updated_at, size=11, color=T.GRAY_TEXT)),
        ]) for t in tickets]
        tickets_table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text("Номер")),
                     ft.DataColumn(ft.Text("Пользователь")),
                     ft.DataColumn(ft.Text("Тема")),
                     ft.DataColumn(ft.Text("Статус")),
                     ft.DataColumn(ft.Text("Приоритет")),
                     ft.DataColumn(ft.Text("Обновлён"))],
            rows=ticket_rows, column_spacing=24, border=T.border_all(),
            heading_row_color=T.GRAY_BG)

        return ft.Column([
            create_card,
            T.card(ft.Column([
                T.section_title(f"Пользователи ({len(users)})",
                                ft.Icons.PERSON),
                ft.Row([users_table], scroll=ft.ScrollMode.AUTO),
            ], spacing=10)),
            T.card(ft.Column([
                T.section_title(f"Тикеты ({len(tickets)})",
                                ft.Icons.BUG_REPORT),
                ft.Row([tickets_table], scroll=ft.ScrollMode.AUTO),
            ], spacing=10)),
        ], spacing=14)

    async def on_create_user(self, e) -> None:
        name = (self.nu_name.value or "").strip()
        email = (self.nu_email.value or "").strip()
        if not name or not email:
            self._set_status("Заполните имя и email", ok=False)
            self._render()
            self.page.update()
            return
        self.busy = True
        self._render()
        self.page.update()
        result = await asyncio.to_thread(ctx.mcp.call, "create_user", {
            "name": name, "email": email,
            "company": self.nu_company.value or "",
            "plan": self.nu_plan.value or "basic",
            "product_version": self.nu_version.value or "",
        })
        self.busy = False
        if isinstance(result, dict) and "error" not in result:
            self._set_status(f"Создан пользователь: {result['name']} "
                             f"({result['email']}), id {result['id']}. "
                             "Можно начинать диалог по этому email.")
        else:
            err = result.get("error", "неизвестная ошибка") \
                if isinstance(result, dict) else str(result)
            self._set_status(f"Пользователь не создан: {err}", ok=False)
        self._render()
        self.page.update()

    # ------------------------------------------------------------------
    # Настройки агента
    # ------------------------------------------------------------------

    def _settings_section(self) -> ft.Control:
        cfg = ctx.agent_configs.get_or_create_default()

        self.model_dd = ft.Dropdown(
            label="Модель DeepSeek", value=cfg.model, width=340,
            options=[ft.DropdownOption(key=m, text=m)
                     for m in AVAILABLE_MODELS],
            border_color=T.GRAY_BORDER, focused_border_color=T.ORANGE)
        self.max_tokens_tf = ft.TextField(
            label="max_tokens", value=str(cfg.max_tokens), width=160,
            border_color=T.GRAY_BORDER, focused_border_color=T.ORANGE)
        self.temp_sl = ft.Slider(min=0, max=1, divisions=10,
                                 value=cfg.temperature, label="{value}",
                                 width=340, active_color=T.ORANGE)
        self.topk_sl = ft.Slider(min=1, max=8, divisions=7,
                                 value=cfg.rag_top_k, label="{value}",
                                 width=340, active_color=T.ORANGE)
        self.threshold_sl = ft.Slider(min=0.3, max=0.9, divisions=12,
                                      value=cfg.rag_threshold,
                                      label="{value}", width=340,
                                      active_color=T.ORANGE)
        self.hist_sl = ft.Slider(min=4, max=24, divisions=10,
                                 value=cfg.history_limit, label="{value}",
                                 width=340, active_color=T.ORANGE)
        self.thinking_sw = ft.Switch(value=cfg.thinking,
                                     active_color=T.ORANGE,
                                     label="Thinking mode (для поддержки "
                                           "обычно не нужен)")
        self.effort_dd = ft.Dropdown(
            label="reasoning_effort", value=cfg.reasoning_effort, width=200,
            options=[ft.DropdownOption(key=r, text=r)
                     for r in REASONING_EFFORTS],
            border_color=T.GRAY_BORDER, focused_border_color=T.ORANGE)
        self.extra_tf = ft.TextField(
            label="Дополнительные инструкции к системному промпту",
            value=cfg.system_prompt_extra, multiline=True, min_lines=3,
            max_lines=6, expand=True, border_color=T.GRAY_BORDER,
            focused_border_color=T.ORANGE, cursor_color=T.ORANGE)

        return T.card(ft.Column([
            T.section_title("Параметры агента", ft.Icons.SETTINGS),
            self.model_dd,
            ft.Row([self.max_tokens_tf, self.effort_dd], spacing=14),
            ft.Text(f"Температура: {cfg.temperature}", size=12,
                    color=T.GRAY_TEXT),
            self.temp_sl,
            ft.Text(f"RAG: top-k = {cfg.rag_top_k}", size=12,
                    color=T.GRAY_TEXT),
            self.topk_sl,
            ft.Text(f"RAG: порог релевантности = {cfg.rag_threshold}",
                    size=12, color=T.GRAY_TEXT),
            self.threshold_sl,
            ft.Text(f"История диалога в контексте: {cfg.history_limit} "
                    "сообщений", size=12, color=T.GRAY_TEXT),
            self.hist_sl,
            self.thinking_sw,
            self.extra_tf,
            ft.FilledButton(content=ft.Text("Сохранить настройки"),
                            icon=ft.Icons.CHECK_CIRCLE, bgcolor=T.GREEN,
                            color=ft.Colors.WHITE, height=44, width=260,
                            on_click=self.on_save_settings),
        ], spacing=8))

    def on_save_settings(self, e) -> None:
        cfg = ctx.agent_configs.get_or_create_default()
        try:
            cfg.model = self.model_dd.value or cfg.model
            cfg.max_tokens = int(self.max_tokens_tf.value or cfg.max_tokens)
            cfg.temperature = round(float(self.temp_sl.value), 2)
            cfg.rag_top_k = int(self.topk_sl.value)
            cfg.rag_threshold = round(float(self.threshold_sl.value), 2)
            cfg.history_limit = int(self.hist_sl.value)
            cfg.thinking = bool(self.thinking_sw.value)
            cfg.reasoning_effort = self.effort_dd.value or "low"
            cfg.system_prompt_extra = self.extra_tf.value or ""
        except ValueError as ex:
            self._set_status(f"Проверьте числовые поля: {ex}", ok=False)
            self._render()
            self.page.update()
            return
        ctx.agent_configs.upsert(cfg)
        ctx.log_service.log("system.config.saved", model=cfg.model,
                            temperature=cfg.temperature,
                            rag_top_k=cfg.rag_top_k,
                            rag_threshold=cfg.rag_threshold,
                            thinking=cfg.thinking)
        self._set_status("Настройки сохранены. Новые значения применятся "
                         "к следующим сообщениям.")
        self._render()
        self.page.update()
