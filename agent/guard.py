"""Инварианты безопасности код-ассистента 1С.

Инварианты (не отключаются, проверяются кодом, а не промптом):
1. Ассистент работает ТОЛЬКО внутри рабочей директории (WORKSPACE_ROOT).
   Любой путь, указывающий за её пределы (абсолютный путь, ../.., симлинк),
   отклоняется с GuardError.
2. Каталог .github — read-only: читать можно, писать нельзя.
3. Удаления не существует как операции: в наборе инструментов нет ни одного
   инструмента удаления, и этот модуль не экспортирует функций удаления.
4. Перезапись существующего файла — опасное действие: выполняется только
   после подтверждения человеком-аналитиком (см. fs_tools).
"""
from __future__ import annotations

from pathlib import Path


class GuardError(Exception):
    """Нарушение инварианта. Сообщение уходит модели как результат инструмента."""


# Каталоги, куда запись запрещена всегда (первый сегмент относительного пути)
READONLY_DIRS = {".github"}


class WorkspaceGuard:
    """Проверяет и нормализует пути относительно рабочей директории."""

    def __init__(self, root: Path):
        root = Path(root).expanduser()
        if not root.exists():
            raise GuardError(f"Рабочая директория не существует: {root}")
        if not root.is_dir():
            raise GuardError(f"Рабочий путь не является директорией: {root}")
        self.root: Path = root.resolve()

    def resolve(self, rel_path: str, *, for_write: bool = False) -> Path:
        """Относительный путь -> абсолютный внутри root. Иначе GuardError.

        for_write=True дополнительно проверяет запрет записи в .github.
        """
        rel_path = (rel_path or "").strip().strip('"').strip("'")
        if not rel_path:
            raise GuardError("Пустой путь")
        candidate = (self.root / rel_path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise GuardError(
                f"ИНВАРИАНТ: путь '{rel_path}' выходит за пределы рабочей "
                f"директории {self.root}. Запрещено.")
        if for_write:
            first = candidate.relative_to(self.root).parts[0] if candidate != self.root else ""
            if first.lower() in READONLY_DIRS:
                raise GuardError(
                    f"ИНВАРИАНТ: запись в '{first}' запрещена "
                    f"(каталог read-only).")
        return candidate

    def rel(self, path: Path) -> str:
        """Абсолютный путь -> относительный (для вывода и журнала)."""
        try:
            return str(Path(path).resolve().relative_to(self.root))
        except ValueError:
            return str(path)
