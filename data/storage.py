"""Низкоуровневое JSON-хранилище: атомарная запись, блокировки.

Весь доступ к данным идёт через репозитории (repositories.py) —
переход на SQLite позже потребует замены только этого слоя.
(Перенесено из проекта «агент_спецификаций_1с» без изменений.)
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


class JsonStore:
    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def path(self, *parts: str) -> Path:
        return self.base.joinpath(*parts)

    def read(self, *parts: str, default: Any = None) -> Any:
        p = self.path(*parts)
        if not p.exists():
            return default
        with _lock_for(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return default

    def write(self, data: Any, *parts: str) -> None:
        p = self.path(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        with _lock_for(p):
            fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, p)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

    def append_jsonl(self, record: dict, *parts: str) -> None:
        p = self.path(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        with _lock_for(p):
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_jsonl(self, *parts: str) -> list[dict]:
        p = self.path(*parts)
        if not p.exists():
            return []
        out = []
        with _lock_for(p):
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        return out

    def clear_jsonl(self, *parts: str) -> None:
        p = self.path(*parts)
        with _lock_for(p):
            with open(p, "w", encoding="utf-8"):
                pass

    def list_dirs(self, *parts: str) -> list[str]:
        p = self.path(*parts)
        if not p.exists():
            return []
        return sorted(d.name for d in p.iterdir() if d.is_dir())

    def list_files(self, *parts: str, suffixes: tuple[str, ...] = ()) -> list[Path]:
        p = self.path(*parts)
        if not p.exists():
            return []
        files = [f for f in p.iterdir() if f.is_file()]
        if suffixes:
            files = [f for f in files if f.suffix.lower() in suffixes]
        return sorted(files)

    def exists(self, *parts: str) -> bool:
        return self.path(*parts).exists()
