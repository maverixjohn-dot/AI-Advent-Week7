"""Страница администрирования: конфигурация, статус инвариантов, статистика."""
from __future__ import annotations

import json
from pathlib import Path

import flet as ft

import config
from ui import theme


def _card(title: str, rows: list[tuple[str, str, str | None]]) -> ft.Control:
    """rows: (метка, значение, цвет значения|None)."""
    items = [ft.Text(title, size=15, weight=ft.FontWeight.BOLD, color=theme.TEXT)]
    for label, value, color in rows:
        items.append(ft.Row([
            ft.Text(label, size=13, color=theme.TEXT_DIM, width=190),
            ft.Text(value, size=13, color=color or theme.TEXT, selectable=True,
                    expand=True),
        ], spacing=8))
    return ft.Container(
        ft.Column(items, spacing=8, tight=True),
        bgcolor=theme.CARD, border=theme.border_all(theme.BORDER),
        border_radius=12, padding=theme.pad_all(16),
    )


class AdminView(ft.Column):
    def __init__(self):
        super().__init__(expand=True, spacing=12,
                         scroll=ft.ScrollMode.AUTO)
        self._mounted = False
        self._body = ft.Column(spacing=12, tight=True,
                               scroll=ft.ScrollMode.AUTO, expand=True)
        header = ft.Row([
            ft.Text("Администрирование", size=18, weight=ft.FontWeight.BOLD,
                    color=theme.TEXT),
            ft.Container(expand=True),
            ft.IconButton(icon=ft.Icons.REFRESH, icon_color=theme.RED,
                          tooltip="Обновить", on_click=lambda e: self.refresh()),
        ])
        self.controls = [
            ft.Container(header, padding=theme.pad_sym(16, 4)),
            ft.Container(self._body, padding=theme.pad_sym(16, 0), expand=True),
        ]

    def did_mount(self):
        self._mounted = True

    def will_unmount(self):
        self._mounted = False

    def _safe_update(self):
        if not self._mounted:
            return
        try:
            self.update()
        except RuntimeError:
            pass

    # ------------------------------------------------------------- данные
    @staticmethod
    def _ok(v: bool) -> tuple[str, str]:
        return ("да", "#1E7D32") if v else ("нет", theme.RED)

    def _status_rows(self) -> list[tuple[str, str, str | None]]:
        ws = config.WORKSPACE_ROOT
        exists = ws.exists() if str(ws) != "." else False
        rows: list[tuple[str, str, str | None]] = []
        val, color = self._ok(exists)
        rows.append(("Рабочая директория существует", val, color))
        if exists:
            val, color = self._ok((ws / "Configuration.xml").exists())
            rows.append(("Configuration.xml (выгрузка 1С)", val, color))
            val, color = self._ok((ws / ".git").exists())
            rows.append(("git-репозиторий", val, color))
            val, color = self._ok((ws / "docs").is_dir())
            rows.append(("Каталог docs/", val, color))
            val, color = self._ok((ws / "README.md").exists())
            rows.append(("README.md (журнал доработок)", val, color))
        problems = config.validate()
        if problems:
            rows.append(("Проблемы конфигурации", "; ".join(problems), theme.RED))
        else:
            rows.append(("Проблемы конфигурации", "нет", "#1E7D32"))
        return rows

    def _journal_rows(self) -> list[tuple[str, str, str | None]]:
        path = config.CHANGES_LOG
        if not path.exists():
            return [("Записей в журнале", "0", None)]
        records = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        counts: dict[str, int] = {}
        for line in records:
            try:
                a = json.loads(line).get("action", "?")
            except json.JSONDecodeError:
                continue
            counts[a] = counts.get(a, 0) + 1
        rows = [("Записей в журнале", str(len(records)), None)]
        for action, n in sorted(counts.items()):
            label = theme.ACTION_LABELS.get(action, action)
            rows.append((f"  — {label}", str(n),
                         theme.ACTION_COLORS.get(action)))
        rows.append(("Файл журнала", str(path), None))
        return rows

    def refresh(self):
        ws = config.WORKSPACE_ROOT
        self._body.controls = [
            _card("Конфигурация", [
                ("Рабочая директория", str(ws) or "не задана", None),
                ("Модель", config.DEEPSEEK_MODEL, None),
                ("API", config.DEEPSEEK_BASE_URL, None),
                ("Режим рассуждений (thinking)",
                 "вкл" if config.DEEPSEEK_THINKING else "выкл", None),
                ("Лимит итераций", str(config.MAX_ITER), None),
                ("DEEPSEEK_API_KEY", "задан" if config.DEEPSEEK_API_KEY
                 else "НЕ ЗАДАН — чат не ответит",
                 "#1E7D32" if config.DEEPSEEK_API_KEY else theme.RED),
            ]),
            _card("Статус рабочей директории", self._status_rows()),
            _card("Инварианты (гарантируются кодом)", [
                ("Запись вне рабочей директории", "отклоняется (GuardError)", "#1E7D32"),
                ("Запись в .github", "отклоняется (read-only)", "#1E7D32"),
                ("Удаление файлов", "операции не существует", "#1E7D32"),
                ("Перезапись существующих", "только с подтверждения аналитика", None),
                ("Журнал доработок", "автоматически в README.md проекта", None),
            ]),
            _card("Журнал изменений", self._journal_rows()),
            _card("Проверка без API-ключа", [
                ("Демо агентского цикла", "python demo.py", None),
                ("Тесты инвариантов", "python -m pytest tests/ -q", None),
            ]),
        ]
        self._safe_update()
