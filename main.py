"""Точка входа ассистента разработчика 1С.

    python main.py            # десктопное окно
    python main.py --web      # web-режим, http://localhost:8550
    python main.py --web --port 9000
"""
from __future__ import annotations

import argparse
import sys

import config


def cli() -> None:
    ap = argparse.ArgumentParser(description="Ассистент разработчика 1С")
    ap.add_argument("--web", action="store_true", help="web-режим вместо десктопного окна")
    ap.add_argument("--port", type=int, default=8550, help="порт web-режима")
    args = ap.parse_args()

    config.setup_logging()
    problems = config.validate()
    for p in problems:
        print(f"ВНИМАНИЕ: {p}", file=sys.stderr)
    if any("DUMP_ROOT" in p for p in problems):
        sys.exit("Задайте A1C_DUMP_ROOT в .env (путь к выгрузке конфигурации)")

    import flet as ft
    from ui.app import main as app_main

    if args.web:
        ft.run(app_main, view=ft.AppView.WEB_BROWSER, port=args.port)
    else:
        ft.run(app_main)


if __name__ == "__main__":
    cli()
