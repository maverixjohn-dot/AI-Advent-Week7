"""Точка входа код-ассистента 1С. По умолчанию — UI (Flet).

    python main.py                          # UI: десктопное окно Flet
    python main.py --web                    # UI в браузере, http://localhost:8550
    python main.py --web --port 9000

    python main.py --cli                    # консоль: интерактивный режим
    python main.py "Найди, где используется Справочник.ФинансовыеПоказатели"
                                            # консоль: одна задача
    python main.py --workspace "C:\\AI Advent\\Week 7\\LifeProgect"
    python main.py --cli --yes              # консоль без подтверждений (рискованно)

Задача ставится на уровне цели — ассистент сам решает, какие файлы
читать и менять. Перезапись существующих файлов требует подтверждения
(в UI — диалог с diff; в консоли — y/n, если не задан --yes).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import config
from agent.assistant import CodeAssistant
from agent.fs_tools import FileTools
from agent.guard import WorkspaceGuard

_SEP = "─" * 70


def _confirm_interactive(action: str, diff: str) -> bool:
    """Подтверждение опасного действия человеком-аналитиком."""
    print(f"\n{_SEP}\nТРЕБУЕТСЯ ПОДТВЕРЖДЕНИЕ: {action}\n{_SEP}")
    if diff:
        print(diff[:8000])
        if len(diff) > 8000:
            print(f"… [diff усечён, всего {len(diff)} символов]")
    while True:
        ans = input("Подтверждаете? [y/n] > ").strip().lower()
        if ans in ("y", "д", "yes", "да"):
            return True
        if ans in ("n", "н", "no", "нет", ""):
            return False


def _ask_interactive(question: str) -> str:
    """Вопрос от ассистента человеку-аналитику."""
    print(f"\n{_SEP}\nАССИСТЕНТ СПРАШИВАЕТ: {question}\n{_SEP}")
    return input("Ваш ответ > ").strip() or "(аналитик не ответил)"


def build_assistant(workspace: Path, assume_yes: bool) -> CodeAssistant:
    guard = WorkspaceGuard(workspace)
    confirm = (lambda _a, _d: True) if assume_yes else _confirm_interactive
    tools = FileTools(guard, confirm=confirm)
    return CodeAssistant(tools, ask=_ask_interactive)


def _run_ui(web: bool, port: int) -> None:
    """Запуск Flet UI. При отсутствии flet — понятная инструкция, а не traceback."""
    try:
        import flet as ft
        from ui.app import main as app_main
    except ImportError:
        sys.exit(
            "Модуль flet не установлен для интерпретатора, которым вы запустили\n"
            "программу:\n"
            f"  {sys.executable}\n\n"
            "Установите зависимости именно в этот интерпретатор:\n"
            f'  "{sys.executable}" -m pip install -r requirements.txt\n\n'
            "Если используете venv (рекомендуется): сначала активируйте его\n"
            r"(Windows PowerShell: .\.venv\Scripts\Activate.ps1), затем "
            "pip install -r requirements.txt — и запускайте из того же venv.\n"
            "При первом десктопном запуске flet сам доустановит flet-desktop "
            "(нужен доступ к PyPI).")
    if web:
        ft.run(app_main, view=ft.AppView.WEB_BROWSER, port=port)
    else:
        ft.run(app_main)


def cli() -> None:
    ap = argparse.ArgumentParser(description="Код-ассистент 1С (эксперт-разработчик)")
    ap.add_argument("task", nargs="?",
                    help="Задача на уровне цели (разово, в консоли); без неё — UI")
    ap.add_argument("--workspace", help="Рабочая директория (иначе CA1C_WORKSPACE_ROOT из env)")
    ap.add_argument("--yes", action="store_true",
                    help="Консоль: автоподтверждение перезаписи файлов (рискованно)")
    ap.add_argument("--ui", action="store_true",
                    help="Десктопное окно Flet (поведение по умолчанию)")
    ap.add_argument("--web", action="store_true", help="UI в браузере")
    ap.add_argument("--cli", action="store_true", help="Консольный режим вместо UI")
    ap.add_argument("--port", type=int, default=8550, help="Порт web-режима")
    args = ap.parse_args()

    config.setup_logging()
    if args.workspace:
        # env — чтобы config.validate() и config.WORKSPACE_ROOT не расходились
        os.environ["CA1C_WORKSPACE_ROOT"] = args.workspace
        config.WORKSPACE_ROOT = Path(args.workspace).expanduser()

    # По умолчанию — UI; консоль: явный --cli или разовая задача аргументом
    if args.web or args.ui or (not args.cli and not args.task):
        _run_ui(web=args.web, port=args.port)
        return

    problems = config.validate()
    for p in problems:
        print(f"ВНИМАНИЕ: {p}", file=sys.stderr)
    if any("CA1C_WORKSPACE_ROOT" in p for p in problems):
        sys.exit("Задайте CA1C_WORKSPACE_ROOT в .env или --workspace")
    if any("DEEPSEEK_API_KEY" in p for p in problems):
        sys.exit("Задайте DEEPSEEK_API_KEY в переменных окружения или .env")

    assistant = build_assistant(config.WORKSPACE_ROOT, args.yes)
    print(f"Рабочая директория: {config.WORKSPACE_ROOT.resolve()}")
    print(f"Модель: {config.DEEPSEEK_MODEL} | подтверждения: "
          f"{'ВЫКЛ (--yes)' if args.yes else 'вкл'}")

    if args.task:
        print(f"\nЗАДАЧА: {args.task}\n{_SEP}")
        print(assistant.run_task(args.task))
        return

    print("Интерактивный режим. Ставьте задачи; 'exit' — выход.\n")
    while True:
        try:
            task = input("Задача > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not task or task.lower() in ("exit", "quit", "выход"):
            break
        print(_SEP)
        try:
            print(assistant.run_task(task))
        except Exception as e:
            print(f"ОШИБКА: {e}", file=sys.stderr)
        print(_SEP)


if __name__ == "__main__":
    cli()
