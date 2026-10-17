"""Светлая цветовая схема приложения: оранжевый, серый, зелёный.

Хелперы border_all / pad_* / ALIGN_* — адаптация под Flet 1.x,
где нет ft.border.all и ft.padding.symmetric.
"""
from __future__ import annotations

import flet as ft

ORANGE = "#E87D1E"          # основной акцент: кнопки, активные элементы
ORANGE_SOFT = "#FBEAD8"     # фон сообщений пользователя
ORANGE_BORDER = "#F0CFA8"
ORANGE_DARK = "#B95F0E"
GREEN = "#2E9E5B"           # успех, источники, «решено»
GREEN_SOFT = "#E2F3E9"
GREEN_BORDER = "#BFE3CE"
GRAY_BG = "#F4F5F7"         # фон страницы
GRAY_CARD = "#FFFFFF"
GRAY_BORDER = "#DDE0E5"
GRAY_TEXT = "#6B7280"       # второстепенный текст
INK = "#23272E"             # основной текст
RED = "#C0392B"
RED_SOFT = "#F9E5E2"
BLUE_GRAY = "#5B7A99"       # llm-события, in_progress

ALIGN_CENTER = ft.Alignment(0, 0)

STATUS_COLORS = {
    "open": ORANGE,
    "in_progress": BLUE_GRAY,
    "resolved": GREEN,
    "closed": GRAY_TEXT,
    "active": GREEN,
}

EVENT_COLORS = {
    "dialog": GRAY_TEXT,
    "rag": GREEN,
    "mcp": ORANGE,
    "llm": BLUE_GRAY,
    "feedback": GREEN,
    "system": GRAY_TEXT,
}


def border_all(width: float = 1, color: str = GRAY_BORDER) -> ft.Border:
    s = ft.BorderSide(width, color)
    return ft.Border(top=s, right=s, bottom=s, left=s)


def left_accent(color: str = GREEN, accent_width: float = 4) -> ft.Border:
    thin = ft.BorderSide(1, GRAY_BORDER)
    return ft.Border(left=ft.BorderSide(accent_width, color),
                     top=thin, right=thin, bottom=thin)


def pad(left: float = 0, top: float = 0, right: float = 0,
        bottom: float = 0) -> ft.Padding:
    return ft.Padding(left, top, right, bottom)


def pad_symmetric(h: float = 0, v: float = 0) -> ft.Padding:
    return ft.Padding(h, v, h, v)


def apply_theme(page: ft.Page) -> None:
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = GRAY_BG
    page.theme = ft.Theme(
        color_scheme_seed=ORANGE,
        visual_density=ft.VisualDensity.COMFORTABLE,
    )


def status_chip(status: str) -> ft.Container:
    color = STATUS_COLORS.get(status, GRAY_TEXT)
    return ft.Container(
        content=ft.Text(status, size=11, color=ft.Colors.WHITE),
        bgcolor=color, border_radius=10,
        padding=pad_symmetric(8, 2),
    )


def event_chip(prefix: str) -> ft.Container:
    color = EVENT_COLORS.get(prefix, GRAY_TEXT)
    return ft.Container(
        content=ft.Text(prefix, size=11, color=ft.Colors.WHITE),
        bgcolor=color, border_radius=10,
        padding=pad_symmetric(8, 2),
    )


def card(content: ft.Control, padding: float = 16, **kwargs) -> ft.Container:
    return ft.Container(
        content=content,
        bgcolor=GRAY_CARD,
        border=border_all(1, GRAY_BORDER),
        border_radius=12,
        padding=padding,
        **kwargs,
    )


def section_title(text: str, icon: str | None = None) -> ft.Row:
    controls: list[ft.Control] = []
    if icon:
        controls.append(ft.Icon(icon, color=ORANGE, size=20))
    controls.append(ft.Text(text, size=16, weight=ft.FontWeight.W_600,
                            color=INK))
    return ft.Row(controls, spacing=8,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)
