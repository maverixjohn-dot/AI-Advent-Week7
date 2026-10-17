"""Конфигурация ассистента разработчика 1С.

Все параметры читаются из переменных окружения (см. .env.example).
.env подхватывается, если установлен python-dotenv; иначе используйте export.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# .env — опционально, без жёсткой зависимости
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("A1C_DATA_DIR", str(BASE_DIR / "data")))
LOG_FILE = DATA_DIR / "assistant.log"

# --- Репозиторий с выгрузкой конфигурации 1С ---
DUMP_ROOT = Path(os.getenv("A1C_DUMP_ROOT", "")).expanduser()

# --- DeepSeek (OpenAI-совместимый API) ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_THINKING = os.getenv("DEEPSEEK_THINKING", "1") == "1"

# --- Эмбеддинги ---
EMBED_MODEL = os.getenv("A1C_EMBED_MODEL", "intfloat/multilingual-e5-large")
EMBED_DEVICE = os.getenv("A1C_EMBED_DEVICE", "cpu")
EMBED_BACKEND = os.getenv("A1C_EMBED_BACKEND", "e5")  # e5 | hash (hash — только для тестов)
EMBED_BATCH = int(os.getenv("A1C_EMBED_BATCH", "16"))

# --- RAG ---
RAG_TOP_K = int(os.getenv("A1C_RAG_TOP_K", "5"))

METADATA_MAP_FILE = DATA_DIR / "metadata_map.json"
STATS_FILE = DATA_DIR / "index_stats.json"


def setup_logging() -> None:
    """Единый лог: файл (для страницы администрирования) + stderr."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if root.handlers:  # повторный вызов (например, из Flet) не дублирует хендлеры
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)


def validate() -> list[str]:
    """Проверка конфигурации перед запуском. Возвращает список проблем."""
    problems: list[str] = []
    # Path("") превращается в "." (cwd) и проходит проверку exists() — поэтому
    # сначала смотрим сырое значение переменной
    raw = os.getenv("A1C_DUMP_ROOT", "").strip()
    if not raw:
        problems.append(
            "A1C_DUMP_ROOT не задан: укажите путь к выгрузке конфигурации "
            "в .env или переменной окружения")
    elif not DUMP_ROOT.exists():
        problems.append(f"A1C_DUMP_ROOT не существует: '{DUMP_ROOT}'")
    elif not (DUMP_ROOT / "Configuration.xml").exists():
        problems.append(f"В {DUMP_ROOT} нет Configuration.xml — это не XML-выгрузка конфигурации")
    if not DEEPSEEK_API_KEY:
        problems.append("DEEPSEEK_API_KEY не задан (нужен для ответов ассистента)")
    return problems
