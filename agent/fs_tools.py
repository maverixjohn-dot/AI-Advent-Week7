"""Файловые инструменты код-ассистента 1С.

Каждый инструмент — метод FileTools, вызываемый из агентского цикла.
Все пути проходят через WorkspaceGuard (инварианты см. guard.py).

Дополнительные правила:
- write_file/append_to_file требуют change_summary: после успешной записи
  строка автоматически попадает в раздел «Журнал доработок» README.md
  рабочей директории (инвариант «свои доработки дописывает в README»
  реализован кодом, а не доверен промпту).
- Перезапись существующего файла — только после подтверждения человеком
  (callback confirm). Создание нового файла подтверждения не требует.
- dry_run=True возвращает diff без записи (сценарий «подготовить diff»).
"""
from __future__ import annotations

import difflib
import fnmatch
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

from .guard import GuardError, WorkspaceGuard

log = logging.getLogger(__name__)

MAX_LIST_ENTRIES = 300
MAX_READ_LINES = 2000
MAX_SEARCH_MATCHES = 80
MAX_OUTPUT_CHARS = 30000

# Подтверждение: (описание действия, diff) -> bool
ConfirmFn = Callable[[str, str], bool]

_CHANGELOG_HEADER = "## Журнал доработок"


def decode_1c_name(name: str) -> str:
    """#U0424#U0438... -> читабельное имя (экранирование имён в XML-выгрузке)."""
    return re.sub(r"#U([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), name)


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [усечено, всего {len(text)} символов]"


class FileTools:
    def __init__(self, guard: WorkspaceGuard, confirm: ConfirmFn | None = None,
                 change_log: Path | None = None):
        self.guard = guard
        self._confirm = confirm or (lambda _action, _diff: False)
        self._change_log = Path(change_log) if change_log else None

    # ------------------------------------------------------------------ utils
    def _display(self, path: Path) -> str:
        """Относительный путь с декодированными #U-именами — для человека."""
        return decode_1c_name(self.guard.rel(path))

    def _log_change(self, path: Path, summary: str) -> None:
        """Строка в «Журнал доработок» README.md рабочей директории."""
        readme = self.guard.root / "README.md"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"- {stamp} — `{self.guard.rel(path)}` — {summary}\n"
        if not readme.exists():
            readme.write_text(
                f"# {self.guard.root.name}\n\n{_CHANGELOG_HEADER}\n\n{line}",
                encoding="utf-8")
            return
        text = readme.read_text(encoding="utf-8")
        if _CHANGELOG_HEADER not in text:
            text = text.rstrip() + f"\n\n{_CHANGELOG_HEADER}\n\n" + line
        else:
            text = text.rstrip() + "\n" + line
        readme.write_text(text, encoding="utf-8")

    @staticmethod
    def _diff(old: str, new: str, rel: str) -> str:
        return "".join(difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"a/{rel}", tofile=f"b/{rel}"))

    def _record(self, action: str, path: Path, summary: str, diff: str) -> None:
        """Событие в JSONL-журнал изменений (для страницы «Журнал» в UI).

        action: created | overwritten | appended | rejected
        """
        if self._change_log is None:
            return
        rec = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "path": self.guard.rel(path),
            "summary": summary,
            "diff": diff,
        }
        try:
            self._change_log.parent.mkdir(parents=True, exist_ok=True)
            with self._change_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:  # журнал UI не должен ломать основную работу
            log.warning("Не удалось писать %s: %s", self._change_log, e)

    # -------------------------------------------------------------- чтение
    def list_files(self, subdir: str = ".", mask: str = "*") -> str:
        """Список файлов и каталогов (рекурсивно, glob-маска на имя файла)."""
        base = self.guard.resolve(subdir)
        if not base.is_dir():
            raise GuardError(f"Не каталог: {subdir}")
        rows: list[str] = []
        for p in sorted(base.rglob("*")):
            if len(rows) >= MAX_LIST_ENTRIES:
                rows.append(f"… [усечено: показано {MAX_LIST_ENTRIES}]")
                break
            if any(part.startswith(".git") for part in p.parts):
                continue
            rel = self.guard.rel(p)
            shown = decode_1c_name(rel)
            if p.is_dir():
                rows.append(f"[каталог] {shown}/")
            elif fnmatch.fnmatch(p.name, mask):
                rows.append(shown)
        if not rows:
            return f"Пусто (путь: {decode_1c_name(subdir)}, маска: {mask})"
        return _clip("\n".join(rows))

    def read_file(self, path: str, offset: int = 1, limit: int = 400) -> str:
        """Чтение файла построчно (offset — с 1, limit — число строк)."""
        p = self.guard.resolve(path)
        if not p.is_file():
            raise GuardError(f"Файл не найден: {decode_1c_name(path)}")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        limit = max(1, min(limit, MAX_READ_LINES))
        chunk = lines[max(0, offset - 1): offset - 1 + limit]
        body = "\n".join(f"{i + offset:>5}\t{s}" for i, s in enumerate(chunk))
        head = f"=== {self._display(p)} (строк: {len(lines)}) ==="
        return _clip(head + "\n" + body)

    def search_files(self, query: str, subdir: str = ".", mask: str = "*",
                     context: int = 2, regex: bool = False) -> str:
        """Поиск подстроки/regex по содержимому файлов (grep по проекту)."""
        base = self.guard.resolve(subdir)
        if not base.is_dir():
            raise GuardError(f"Не каталог: {subdir}")
        try:
            pattern = re.compile(query if regex else re.escape(query), re.IGNORECASE)
        except re.error as e:
            raise GuardError(f"Некорректный regex: {e}")
        out: list[str] = []
        matches = 0
        for p in sorted(base.rglob("*")):
            if matches >= MAX_SEARCH_MATCHES:
                out.append(f"… [усечено: показано {MAX_SEARCH_MATCHES} совпадений]")
                break
            if not p.is_file() or not fnmatch.fnmatch(p.name, mask):
                continue
            if any(part.startswith(".git") for part in p.parts):
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                if not pattern.search(line):
                    continue
                matches += 1
                lo, hi = max(0, i - context), min(len(lines), i + context + 1)
                out.append(f"--- {self._display(p)}:{i + 1}")
                out.extend(f"  {j + 1:>5} {lines[j]}" for j in range(lo, hi))
                if matches >= MAX_SEARCH_MATCHES:
                    break
        if not out:
            return f"Совпадений нет: «{query}» (путь: {decode_1c_name(subdir)}, маска: {mask})"
        return _clip(f"Совпадений: {matches}\n" + "\n".join(out))

    # -------------------------------------------------------------- запись
    def write_file(self, path: str, content: str, change_summary: str,
                   dry_run: bool = False) -> str:
        """Создать файл или перезаписать целиком.

        Перезапись существующего — только после подтверждения аналитиком.
        dry_run=True — показать diff, ничего не записывать.
        """
        if not change_summary.strip():
            raise GuardError("change_summary обязателен (уйдёт в журнал README)")
        p = self.guard.resolve(path, for_write=True)
        exists = p.exists()
        old = p.read_text(encoding="utf-8", errors="replace") if exists else ""
        diff = self._diff(old, content, self.guard.rel(p)) if exists else \
            f"Новый файл: {self._display(p)} ({len(content)} символов)"

        if dry_run:
            return _clip(f"DRY-RUN, ничего не записано.\n{diff}")

        if exists:
            action = f"Перезаписать существующий файл {self._display(p)}?"
            if not self._confirm(action, diff):
                self._record("rejected", p, change_summary, diff)
                return f"ОТКАЗАНО аналитиком: {self._display(p)} не изменён."
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        self._log_change(p, change_summary)
        self._record("overwritten" if exists else "created", p, change_summary, diff)
        log.info("Записан %s (%d симв.)", p, len(content))
        prefix = "Перезаписан" if exists else "Создан"
        return _clip(f"{prefix} файл: {self._display(p)}\n"
                     f"Запись добавлена в журнал README.md.\n{diff}")

    def append_to_file(self, path: str, content: str, change_summary: str,
                       dry_run: bool = False) -> str:
        """Дописать в конец файла (changelog, README, ADR-лог)."""
        if not change_summary.strip():
            raise GuardError("change_summary обязателен (уйдёт в журнал README)")
        p = self.guard.resolve(path, for_write=True)
        old = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        new = old + ("" if old.endswith("\n") or not old else "\n") + content
        diff = self._diff(old, new, self.guard.rel(p))
        if dry_run:
            return _clip(f"DRY-RUN, ничего не записано.\n{diff}")
        if p.exists():
            action = f"Дописать в существующий файл {self._display(p)}?"
            if not self._confirm(action, diff):
                self._record("rejected", p, change_summary, diff)
                return f"ОТКАЗАНО аналитиком: {self._display(p)} не изменён."
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new, encoding="utf-8")
        self._log_change(p, change_summary)
        self._record("appended", p, change_summary, diff)
        log.info("Дописан %s (+%d симв.)", p, len(content))
        return _clip(f"Дописан файл: {self._display(p)}\n"
                     f"Запись добавлена в журнал README.md.\n{diff}")
