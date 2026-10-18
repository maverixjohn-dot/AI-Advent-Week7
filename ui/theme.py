"""Светлая тема UI в фирменных цветах 1С: жёлтый #FFF200 + красный #E2001A.

Семантика:
- жёлтый — шапка, выделение, пузырь аналитика, нейтральные акценты;
- красный — логотип «1C», основные кнопки действия, деструктивные операции;
- светлый тёплый фон, белые карточки, тёмно-серый текст.
"""
from __future__ import annotations

import flet as ft

YELLOW = "#FFF200"        # фирменный жёлтый 1С
YELLOW_SOFT = "#FFFBE0"   # пузырь аналитика / мягкая подложка
YELLOW_EDGE = "#E8DC00"   # кромка/обводка жёлтого
RED = "#E2001A"           # фирменный красный 1С
RED_DARK = "#A80014"
RED_SOFT = "#FDE7EA"      # подложка для деструктивных/важных
BG = "#FAF9F5"            # светлый тёплый фон страницы
CARD = "#FFFFFF"
BORDER = "#E7E4DB"        # тёплая серая рамка
TEXT = "#26241F"          # почти чёрный, тёплый
TEXT_DIM = "#7A766B"
MONO_BG = "#26241F"       # подложка diff/логов
MONO_FG = "#F2EFE6"

ACTION_COLORS = {
    "created": "#1E7D32",      # зелёный — создан
    "overwritten": RED,        # красный — перезаписан (опасная операция)
    "appended": "#8A6D00",     # тёмно-жёлтый — дописан
    "rejected": TEXT_DIM,      # серый — отклонено аналитиком
}
ACTION_LABELS = {
    "created": "Создан",
    "overwritten": "Перезаписан",
    "appended": "Дописан",
    "rejected": "Отклонено",
}


def pad_all(v: float) -> ft.Padding:
    return ft.Padding(v, v, v, v)


def pad_sym(h: float, v: float) -> ft.Padding:
    return ft.Padding(h, v, h, v)


def border_all(color: str) -> ft.Border:
    s = ft.BorderSide(1, color)
    return ft.Border(s, s, s, s)


def logo_1c(size: int = 34) -> ft.Control:
    """Жёлтый квадрат с красной надписью «1C» — фирменный знак."""
    return ft.Container(
        ft.Text("1C", size=size // 2, weight=ft.FontWeight.BOLD, color=RED),
        width=size, height=size, bgcolor=YELLOW, border_radius=6,
        alignment=ft.Alignment(0, 0),
        border=border_all(YELLOW_EDGE),
    )


def apply(page: ft.Page) -> None:
    page.bgcolor = BG
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=RED,
            on_primary=ft.Colors.WHITE,
            secondary=YELLOW,
            on_secondary=TEXT,
            surface=CARD,
            on_surface=TEXT,
        )
    )
    page.padding = 0
