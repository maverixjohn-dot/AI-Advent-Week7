"""MCP-сервер ассистента разработчика 1С. Транспорт: stdio (локальный запуск).

Инструменты:
- get_current_branch / git_diff / list_files — git-контекст репозитория выгрузки;
- objects_tree / object_info / objects_list — структура конфигурации (карта метаданных);
- rag_search — векторный поиск по документации и коду.

Запуск: python -m mcp_server.server   (обычно порождается клиентом по stdio)
"""
from __future__ import annotations

import fnmatch
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP

import config
from indexer.embeddings import get_encoder
from indexer.store import VectorStore

log = logging.getLogger(__name__)
mcp = FastMCP("assistant-1c")

# ---------------------------------------------------------------------------
# Ленивые синглтоны данных
# ---------------------------------------------------------------------------
_map_cache: dict | None = None
_store_cache: VectorStore | None = None


def _load_map() -> dict:
    global _map_cache
    if _map_cache is None:
        if not config.METADATA_MAP_FILE.exists():
            from indexer.indexer import run_index
            log.info("Карта метаданных отсутствует — запускаю индексацию")
            run_index(full=False)
        import json
        _map_cache = json.loads(config.METADATA_MAP_FILE.read_text(encoding="utf-8"))
    return _map_cache


def _load_store() -> VectorStore | None:
    global _store_cache
    if _store_cache is None:
        _store_cache = VectorStore.load(config.DATA_DIR)
    return _store_cache


def _repo():
    import git
    root = config.DUMP_ROOT
    if not root or not (root / ".git").exists():
        raise RuntimeError(
            f"'{root}' не является git-репозиторием. Выполните там: "
            f"git init && git add . && git commit -m init")
    repo = git.Repo(root)
    # иначе кириллические пути приходят в виде "\320\244..." и ломают фильтры
    repo.git.config("core.quotepath", "false")
    return repo


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

@mcp.tool
def get_current_branch() -> str:
    """Текущая git-ветка репозитория выгрузки конфигурации."""
    try:
        repo = _repo()
    except RuntimeError as e:
        return f"Ошибка: {e}"
    branch = repo.active_branch.name
    try:
        last = repo.head.commit
        return f"Ветка: {branch}\nПоследний коммит: {last.hexsha[:7]} — {last.message.strip()}"
    except ValueError:
        return f"Ветка: {branch} (коммитов пока нет)"


@mcp.tool
def git_diff(file_path: str = "", staged: bool = False) -> str:
    """Diff рабочего дерева (или конкретного файла) репозитория выгрузки.

    file_path — путь относительно корня репозитория; пусто — весь diff.
    staged — True для diff --cached (проиндексированные изменения).
    """
    try:
        repo = _repo()
    except RuntimeError as e:
        return f"Ошибка: {e}"
    args = ["--cached"] if staged else []
    if file_path:
        args += ["--", file_path]
    diff = repo.git.diff(*args)
    if not diff.strip():
        return "Изменений нет."
    if len(diff) > 12000:
        diff = diff[:12000] + "\n\n... (diff обрезан, показаны первые 12000 символов)"
    return f"```diff\n{diff}\n```"


@mcp.tool
def list_files(subdir: str = "", mask: str = "*") -> str:
    """Список файлов репозитория выгрузки (по git). mask — glob, напр. '*.bsl'."""
    try:
        repo = _repo()
    except RuntimeError as e:
        return f"Ошибка: {e}"
    files = repo.git.ls_files(subdir or ".").splitlines()
    if mask != "*":
        files = [f for f in files if fnmatch.fnmatch(Path(f).name, mask)]
    if not files:
        return "Файлы не найдены."
    if len(files) > 200:
        shown, note = files[:200], f"\n... и ещё {len(files) - 200}"
    else:
        shown, note = files, ""
    return "\n".join(shown) + note


# ---------------------------------------------------------------------------
# Структура конфигурации
# ---------------------------------------------------------------------------

def _find_object(mmap: dict, name: str) -> dict | None:
    """'Документ.ФинансовыйФакт', 'РегистрСведений.Настройка...' или просто 'ФинансовыйФакт'."""
    from indexer.parser_1c import norm_type
    name = name.strip()
    if "." in name:
        t, n = name.split(".", 1)
        t = norm_type(t)
        for o in mmap["objects"]:
            if o["type"].lower() == t.lower() and o["name"].lower() == n.lower():
                return o
        return None
    for o in mmap["objects"]:
        if o["name"].lower() == name.lower():
            return o
    return None


@mcp.tool
def objects_tree() -> str:
    """Дерево объектов конфигурации по подсистемам."""
    mmap = _load_map()
    cfg = mmap["configuration"]
    lines = [f"Конфигурация «{cfg['name']}» ({cfg['run_mode']}, совместимость {cfg['compatibility']})"]

    subs = {s["name"]: s for s in mmap["subsystems"]}

    def render(name: str, indent: int):
        s = subs[name]
        lines.append("  " * indent + f"▸ {s['name']}" + (f" — {s['synonym']}" if s["synonym"] else ""))
        for item in s["content"]:
            lines.append("  " * (indent + 1) + "• " + item)
        for child in mmap["subsystems"]:
            if child["parent"] == name:
                render(child["name"], indent + 1)

    for s in mmap["subsystems"]:
        if not s["parent"]:
            render(s["name"], 1)
    return "\n".join(lines)


@mcp.tool
def object_info(name: str) -> str:
    """Состав объекта метаданных: реквизиты, табличные части, измерения/ресурсы,
    формы, макеты, модули, движения. name — 'ФинансовыйФакт' или 'Документ.ФинансовыйФакт'."""
    from indexer.parser_1c import object_card
    mmap = _load_map()
    o = _find_object(mmap, name)
    if o is None:
        known = ", ".join(f"{x['type']}.{x['name']}" for x in mmap["objects"])
        return f"Объект '{name}' не найден. Известные объекты: {known}"
    card = object_card(o)
    mods = o.get("modules", [])
    if mods:
        card += "\n\nФайлы модулей:\n" + "\n".join(f"- {m['path']}" for m in mods)
    card += f"\n\nФайл: {o['path']}"
    return card


@mcp.tool
def objects_list(object_type: str = "", name_mask: str = "", subsystem: str = "") -> str:
    """Объекты по фильтру: тип (Catalog/Справочник/Document/...), маска имени (*Финанс*),
    подсистема. Все параметры необязательны, комбинируются по И."""
    from indexer.parser_1c import norm_type
    mmap = _load_map()
    if object_type:
        object_type = norm_type(object_type)
    res = []
    for o in mmap["objects"]:
        if object_type and o["type"].lower() != object_type.lower():
            continue
        if name_mask and not fnmatch.fnmatch(o["name"].lower(), name_mask.lower()):
            continue
        if subsystem and subsystem not in o.get("subsystems", []):
            continue
        res.append(o)
    if not res:
        return "Объекты по фильтру не найдены."
    lines = [f"Найдено: {len(res)}"]
    for o in res:
        lines.append(f"• {o['type']}.{o['name']}" + (f" — {o['synonym']}" if o["synonym"] else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------

@mcp.tool
def rag_search(query: str, top_k: int = 0) -> str:
    """Семантический поиск по документации, карточкам объектов и коду модулей.
    Возвращает top_k релевантных фрагментов с источниками."""
    store = _load_store()
    if store is None or not store.chunks:
        return "Индекс пуст. Выполните переиндексацию (/reindex или страница администрирования)."
    k = top_k or config.RAG_TOP_K
    qvec = get_encoder().encode_query(query)
    hits = store.search(qvec, k)
    if not hits:
        return "Ничего не найдено."
    parts = []
    for chunk, score in hits:
        parts.append(f"### {chunk['source']} (score {score:.3f})\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)


if __name__ == "__main__":
    config.setup_logging()
    problems = [p for p in config.validate() if "DEEPSEEK" not in p]  # серверу ключ не нужен
    if problems:
        for p in problems:
            log.error(p)
        sys.exit(1)
    mcp.run()
