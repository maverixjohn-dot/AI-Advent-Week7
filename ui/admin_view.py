"""Страница администрирования: статус индекса, переиндексация, логи."""
from __future__ import annotations

import asyncio
import json
import logging
import sys

import flet as ft

import config
from ui import theme

log = logging.getLogger(__name__)

LOG_TAIL_LINES = 300


def _stat_card(title: str, value: str, subtitle: str = "") -> ft.Control:
    return ft.Card(
        content=ft.Container(
            ft.Column([
                ft.Text(title, size=12, color=theme.TEXT_DIM),
                ft.Text(value, size=20, weight=ft.FontWeight.W_600, color=theme.TEXT,
                        selectable=True),
                ft.Text(subtitle, size=11, color=theme.TEXT_DIM) if subtitle else ft.Container(),
            ], spacing=2),
            padding=16, width=250,
        ),
    )


class AdminView(ft.Column):
    def __init__(self):
        super().__init__(expand=True, spacing=16, scroll=ft.ScrollMode.AUTO)
        self.stats_row = ft.Row(wrap=True, spacing=12, run_spacing=12)
        self.status_text = ft.Text("", color=theme.TEXT_DIM, size=12, selectable=True)
        self.log_view = ft.Text("", selectable=True, size=12, color=theme.LOG_FG)

        reindex_inc = ft.FilledButton("Инкрементальная переиндексация", icon=ft.Icons.REFRESH,
                                      on_click=lambda e: self.page.run_task(self._reindex, e, False))
        reindex_full = ft.OutlinedButton("Полная переиндексация", icon=ft.Icons.RESTART_ALT,
                                         on_click=lambda e: self.page.run_task(self._reindex, e, True))
        refresh = ft.TextButton("Обновить логи", icon=ft.Icons.ARTICLE,
                                on_click=lambda e: self.refresh())

        self.controls = [
            ft.Text("Администрирование", size=22, weight=ft.FontWeight.W_600,
                    color=theme.TEXT),
            self.stats_row,
            ft.Row([reindex_inc, reindex_full], spacing=12),
            self.status_text,
            ft.Row([ft.Text("Логи", size=16, weight=ft.FontWeight.W_600,
                            color=theme.TEXT), refresh],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(self.log_view, bgcolor=theme.LOG_BG, border_radius=10,
                         padding=14, expand=True),
        ]

    def did_mount(self):
        self.refresh()

    # --- данные ---
    def refresh(self):
        self.stats_row.controls = self._build_stats()
        self.log_view.value = self._read_log()
        self.update()

    def _build_stats(self) -> list[ft.Control]:
        cards: list[ft.Control] = []
        if config.STATS_FILE.exists():
            s = json.loads(config.STATS_FILE.read_text(encoding="utf-8"))
            cards += [
                _stat_card("Объектов метаданных", str(s.get("objects", "—")),
                           f"подсистем: {s.get('subsystems', '—')}"),
                _stat_card("Чанков в индексе", str(s.get("chunks_total", "—")),
                           f"последний прогон: +{s.get('chunks_reindexed', '—')}"),
                _stat_card("Последняя индексация", s.get("finished_at", "—"),
                           f"режим: {s.get('mode', '—')}, {s.get('duration_sec', '—')} с"),
                _stat_card("Эмбеддинги", s.get("embed_model", "—"), "локально, CPU"),
            ]
        else:
            cards.append(_stat_card("Индекс", "не построен",
                                    "запустите переиндексацию"))
        cards += [
            _stat_card("LLM", config.DEEPSEEK_MODEL,
                       f"thinking: {'вкл' if config.DEEPSEEK_THINKING else 'выкл'}"),
            _stat_card("Репозиторий выгрузки", str(config.DUMP_ROOT) or "не задан",
                       self._branch()),
        ]
        return cards

    def _branch(self) -> str:
        try:
            import git
            repo = git.Repo(config.DUMP_ROOT)
            return f"ветка: {repo.active_branch.name}"
        except Exception:
            return "не git-репозиторий"

    def _read_log(self) -> str:
        if not config.LOG_FILE.exists():
            return "Лог-файл пока не создан."
        lines = config.LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-LOG_TAIL_LINES:]) or "(пусто)"

    # --- переиндексация ---
    async def _reindex(self, e: ft.ControlEvent, full: bool):
        e.control.disabled = True
        self.status_text.value = "Индексация выполняется…"
        self.update()
        args = [sys.executable, "-m", "indexer.indexer"] + (["--full"] if full else [])
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(config.BASE_DIR),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        e.control.disabled = False
        if proc.returncode == 0:
            stats = json.loads(stdout.decode())
            self.status_text.value = (
                f"Готово за {stats['duration_sec']} с: чанков {stats['chunks_total']}, "
                f"переиндексировано {stats['chunks_reindexed']}")
        else:
            log.error("Индексация из админки упала: %s", stderr.decode()[-2000:])
            self.status_text.value = "Ошибка индексации — см. логи."
        self.refresh()
