"""Оранжево-серая светлая тема UI."""
from __future__ import annotations

import flet as ft

ORANGE = "#E8710A"        # основной акцент
ORANGE_DARK = "#B95C00"
ORANGE_SOFT = "#FDEBD7"   # пузырь пользователя
BG = "#F4F4F5"            # светло-серый фон страницы
CARD = "#FFFFFF"
BORDER = "#E4E4E7"        # серая рамка
TEXT = "#27272A"          # тёмно-серый текст
TEXT_DIM = "#71717A"
LOG_BG = "#27272A"        # тёмная подложка логов
LOG_FG = "#E4E4E7"


def pad_all(v: float) -> ft.Padding:
    return ft.Padding(v, v, v, v)


def pad_sym(h: float, v: float) -> ft.Padding:
    return ft.Padding(h, v, h, v)


def border_all(color: str) -> ft.Border:
    s = ft.BorderSide(1, color)
    return ft.Border(s, s, s, s)


def apply(page: ft.Page) -> None:
    page.bgcolor = BG
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=ORANGE,
            on_primary=ft.Colors.WHITE,
            surface=CARD,
            on_surface=TEXT,
            secondary=TEXT_DIM,
        )
    )
    page.padding = 0
