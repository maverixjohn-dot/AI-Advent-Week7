"""Страница «Журнал изменений»: в какие файлы ассистент внёс правки.

Источник — JSONL-журнал (config.CHANGES_LOG), который FileTools пишет
при каждой записи/отказе. README.md рабочей директории остаётся
человекочитаемым журналом в самом проекте; эта страница — удобный
просмотр с diff по каждому событию.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import flet as ft

from agent.fs_tools import decode_1c_name
from ui import theme

log = logging.getLogger(__name__)


def _read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


class LogsView(ft.Column):
    def __init__(self, log_path: Path):
        super().__init__(expand=True, spacing=0)
        self._log_path = Path(log_path)
        self._mounted = False
        self._build()

    # --- монтирование: update() у контрола вне страницы падает (гонки с
    # фоновым обновлением после завершения задачи в чате) ---
    def did_mount(self):
        self._mounted = True

    def will_unmount(self):
        self._mounted = False

    def _safe_update(self):
        if not self._mounted:
            return
        try:
            self.update()
        except RuntimeError:  # контроль снят со страницы между проверкой и update
            pass

    def _build(self) -> None:
        self._list = ft.ListView(expand=True, spacing=8,
                                 padding=theme.pad_sym(16, 8))
        self._stats = ft.Text("", color=theme.TEXT_DIM, size=12)
        header = ft.Row([
            ft.Text("Журнал изменений файлов", size=18, weight=ft.FontWeight.BOLD,
                    color=theme.TEXT),
            ft.Container(expand=True),
            self._stats,
            ft.IconButton(icon=ft.Icons.REFRESH, icon_color=theme.RED,
                          tooltip="Обновить", on_click=lambda e: self.refresh()),
        ])
        self.controls = [
            ft.Container(header, padding=theme.pad_sym(16, 8)),
            ft.Divider(height=1, color=theme.BORDER),
            ft.Container(self._list, expand=True),
        ]

    # ------------------------------------------------------------------ ui
    def _badge(self, action: str) -> ft.Control:
        color = theme.ACTION_COLORS.get(action, theme.TEXT_DIM)
        return ft.Container(
            ft.Text(theme.ACTION_LABELS.get(action, action), size=11,
                    color=ft.Colors.WHITE, weight=ft.FontWeight.W_500),
            bgcolor=color, border_radius=10, padding=theme.pad_sym(8, 3),
        )

    def _diff_dialog(self, rec: dict):
        diff = rec.get("diff") or "(diff не записан)"
        dlg = ft.AlertDialog(
            title=ft.Text(decode_1c_name(rec.get("path", "")),
                          weight=ft.FontWeight.BOLD, size=14),
            content=ft.Container(
                ft.Column([ft.Text(diff, font_family="monospace", size=11,
                                   color=theme.MONO_FG, selectable=True)],
                          scroll=ft.ScrollMode.AUTO, tight=True),
                bgcolor=theme.MONO_BG, border_radius=8, padding=10,
                width=760, height=420,
            ),
            actions=[ft.TextButton("Закрыть",
                                   style=ft.ButtonStyle(color=theme.TEXT_DIM),
                                   on_click=lambda e: self._close(dlg))],
        )
        self.page.show_dialog(dlg)

    def _close(self, dlg):
        try:
            self.page.pop_dialog()
        except Exception:
            dlg.open = False
            self.page.update()

    def _row(self, rec: dict) -> ft.Control:
        return ft.Container(
            ft.Row([
                self._badge(rec.get("action", "")),
                ft.Column([
                    ft.Text(decode_1c_name(rec.get("path", "")), size=13,
                            weight=ft.FontWeight.W_500, color=theme.TEXT,
                            selectable=True),
                    ft.Text(rec.get("summary", ""), size=12, color=theme.TEXT_DIM,
                            selectable=True),
                ], spacing=2, expand=True),
                ft.Text(rec.get("ts", ""), size=11, color=theme.TEXT_DIM),
                ft.TextButton("diff", data=rec, on_click=lambda e: self._diff_dialog(e.control.data),
                              style=ft.ButtonStyle(color=theme.RED_DARK)),
            ], spacing=12, alignment=ft.MainAxisAlignment.START),
            bgcolor=theme.CARD, border=theme.border_all(theme.BORDER),
            border_radius=10, padding=theme.pad_sym(12, 10),
        )

    def mounted_refresh(self):
        """Обновление извне (после завершения задачи в чате): только если смонтирован."""
        if self._mounted:
            self.refresh()

    def refresh(self):
        records = _read_records(self._log_path)
        self._list.controls.clear()
        if not records:
            self._list.controls.append(ft.Container(
                ft.Text("Изменений пока нет — поставьте задачу в чате.",
                        color=theme.TEXT_DIM),
                padding=40, alignment=ft.Alignment(0, 0)))
        else:
            for rec in reversed(records):  # свежие сверху
                self._list.controls.append(self._row(rec))
            counts: dict[str, int] = {}
            for r in records:
                counts[r["action"]] = counts.get(r["action"], 0) + 1
            parts = [f"{theme.ACTION_LABELS.get(a, a).lower()}: {n}"
                     for a, n in sorted(counts.items())]
            self._stats.value = f"всего {len(records)} ({', '.join(parts)})"
        self._safe_update()
