"""Конфигурация код-ассистента 1С.

Все параметры — из переменных окружения (см. .env.example).
.env подхватывается, если установлен python-dotenv; переменные окружения
приоритетнее значений из файла.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("CA1C_DATA_DIR", str(BASE_DIR / "data")))
# Структурированный журнал изменений (JSONL) — источник страницы «Журнал» в UI.
# Пишется рядом с авто-журналом в README.md рабочей директории.
CHANGES_LOG = DATA_DIR / "changes.jsonl"

# --- Рабочая директория ассистента (единственная, куда он может писать) ---
# У пользователя-аналитика: C:\AI Advent\Week 7\LifeProgect
WORKSPACE_ROOT = Path(os.getenv("CA1C_WORKSPACE_ROOT", "")).expanduser()

# --- DeepSeek (OpenAI-совместимый API) ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_THINKING = os.getenv("DEEPSEEK_THINKING", "1") == "1"

# --- Агентский цикл ---
MAX_ITER = int(os.getenv("CA1C_MAX_ITER", "15"))


def setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def validate() -> list[str]:
    """Проверка конфигурации перед запуском. Возвращает список проблем."""
    problems: list[str] = []
    raw = os.getenv("CA1C_WORKSPACE_ROOT", "").strip()
    if not raw:
        problems.append(
            "CA1C_WORKSPACE_ROOT не задан: укажите путь к рабочей директории "
            "проекта в .env или переменной окружения "
            "(например, C:\\AI Advent\\Week 7\\LifeProgect)")
    elif not WORKSPACE_ROOT.exists():
        problems.append(f"CA1C_WORKSPACE_ROOT не существует: '{WORKSPACE_ROOT}'")
    elif not (WORKSPACE_ROOT / "Configuration.xml").exists():
        # Не блокируем: ассистент может работать с любым проектом, но предупреждаем
        log = logging.getLogger(__name__)
        log.warning("В %s нет Configuration.xml — это не XML-выгрузка "
                    "конфигурации 1С, работаем как с обычным проектом", WORKSPACE_ROOT)
    if not DEEPSEEK_API_KEY:
        problems.append("DEEPSEEK_API_KEY не задан (нужен для ответов ассистента)")
    return problems
