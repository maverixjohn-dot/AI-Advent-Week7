"""AI-ревью изменений (PR) конфигурации 1С.

Headless-режим для CI (GitHub Action) и локального запуска:

    python -m agent.review --base main                      # ревью в stdout
    python -m agent.review --base origin/main --out review.md

Что делает:
1. Берёт изменённые файлы и diff `base...HEAD` (семантика PR: от точки
   расхождения ветки с base).
2. Отображает изменённые файлы на объекты метаданных (по карте метаданных).
3. Собирает контекст из RAG: требования к код-ревью (docs), карточки
   затронутых объектов, чанки изменённых модулей.
4. Вызывает DeepSeek с фиксированной структурой ответа:
   потенциальные баги / архитектурные проблемы / рекомендации.

Индекс RAG должен быть построен заранее (python -m indexer.indexer).
Без индекса ревью всё равно работает, но без RAG-контекста (только diff +
карточки объектов).

Коды выхода: 0 — ok (включая «изменений нет»); 2 — проблема конфигурации/git;
3 — нет DEEPSEEK_API_KEY.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from indexer import parser_1c

log = logging.getLogger(__name__)

# Лимиты: diff XML-выгрузки многословен, обрезаем с явным предупреждением
MAX_DIFF_CHARS = int(os.getenv("A1C_REVIEW_MAX_DIFF", "50000"))
MAX_FILE_CHARS = int(os.getenv("A1C_REVIEW_MAX_FILE_DIFF", "15000"))
MAX_RULES_CHUNKS = 4
MAX_MODULE_CHUNKS = 6

REVIEW_SYSTEM = """Ты — строгий ревьюер конфигурации 1С:Enterprise (код на русском, bsl).
Ревьюируешь diff pull request'а. Правила:

- Опирайся на требования к код-ревью из контекста (раздел «Требования») и на
  карточки затронутых объектов. Не выдумывай объекты и реквизиты, которых нет
  в контексте или diff.
- Каждое замечание привязывай к файлу и, если возможно, к месту в diff
  (имя процедуры / фрагмент строки).
- Замечания ранжируй: сначала критичные (баги, потеря данных, падения), затем
  архитектура, затем рекомендации. Мелкий стиль — только если он скрывает баг.
- Если замечаний в разделе нет — напиши «не выявлено».
- Отвечай строго в формате markdown с разделами:
  ## Потенциальные баги
  ## Архитектурные проблемы
  ## Рекомендации
  ## Общая оценка
  (одна строка: approve / comment / request changes + одно предложение почему)
"""


def _repo():
    import git
    root = config.DUMP_ROOT
    if not root or not (root / ".git").exists():
        raise RuntimeError(f"'{root}' не git-репозиторий (A1C_DUMP_ROOT)")
    repo = git.Repo(root)
    try:
        repo.git.config("core.quotepath", "false")  # кириллические пути
    except Exception:
        pass
    return repo


def changed_files(repo, base: str) -> list[tuple[str, str]]:
    """[(status, path)] по git diff --name-status base...HEAD."""
    out = repo.git.diff("--name-status", f"{base}...HEAD")
    files: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status, path = parts[0], parts[-1]  # при rename: R100 old new -> берём new
        files.append((status, path))
    return files


def diff_text(repo, base: str) -> str:
    """Diff base...HEAD с покомпонентной обрезкой: сначала по файлу, потом глобально."""
    full = repo.git.diff(f"{base}...HEAD")
    if len(full) <= MAX_DIFF_CHARS:
        return full
    # разбиваем на файловые секции и обрезаем каждую
    sections = full.split("diff --git ")
    head, file_sections = sections[0], ["diff --git " + s for s in sections[1:]]
    truncated = []
    budget = MAX_DIFF_CHARS
    for s in file_sections:
        if len(s) > MAX_FILE_CHARS:
            s = s[:MAX_FILE_CHARS] + f"\n... (diff файла обрезан до {MAX_FILE_CHARS} символов)\n"
        if budget - len(s) < 0:
            truncated.append(f"\n... (пропущены оставшиеся {len(file_sections) - len(truncated)} "
                             f"файлов — превышен лимит {MAX_DIFF_CHARS} символов)\n")
            break
        truncated.append(s)
        budget -= len(s)
    return head + "".join(truncated)


def map_files_to_objects(files: list[tuple[str, str]], mmap: dict) -> list[dict]:
    """Изменённые файлы -> объекты метаданных (по путям выгрузки)."""
    touched: dict[str, dict] = {}
    for _status, path in files:
        p = Path(path)
        for o in mmap["objects"]:
            obj_xml = o["path"]                       # Documents/ФинансовыйФакт.xml
            obj_dir = obj_xml[:-4] if obj_xml.endswith(".xml") else obj_xml
            if path == obj_xml or path.startswith(obj_dir + "/"):
                touched[f"{o['type']}.{o['name']}"] = o
    return sorted(touched.values(), key=lambda o: (o["type"], o["name"]))


def rag_context(store, query_encoder, changed: set[str]) -> str:
    """Контекст из RAG: требования к ревью + чанки изменённых файлов."""
    if store is None or query_encoder is None:
        return "(индекс RAG недоступен — контекст ограничен карточками объектов)"
    blocks: list[str] = []

    q_vec = query_encoder.encode_query(
        "требования к код-ревью 1С чек-лист ревьюера запросы транзакции "
        "обработка ошибок производительность")
    rules = store.search(q_vec, top_k=MAX_RULES_CHUNKS)
    if rules:
        blocks.append("### Требования к код-ревью (из документации проекта)\n"
                      + "\n\n".join(f"[{c['source']}] {c['text']}" for c, _s in rules))

    mod_chunks = [c for c in store.chunks if c["source"] in changed][:MAX_MODULE_CHUNKS]
    if mod_chunks:
        blocks.append("### Код затронутых модулей (текущее состояние в ветке)\n"
                      + "\n\n".join(f"[{c['source']}] {c['text']}" for c in mod_chunks))
    return "\n\n".join(blocks) if blocks else "(RAG не нашёл релевантного контекста)"


def build_prompt(base: str, repo, files: list[tuple[str, str]],
                 objects: list[dict], context: str, diff: str) -> str:
    head = repo.head.commit
    try:
        branch = repo.active_branch.name
    except TypeError:
        # detached HEAD (git worktree, GitHub Actions checkout)
        branch = f"detached@{head.hexsha[:7]}"
    flist = "\n".join(f"  {st}\t{p}" for st, p in files)
    cards = "\n\n".join(parser_1c.object_card(o) for o in objects) or "(не затронуты)"
    return f"""Ревью pull request'а конфигурации 1С «Целеполагание».

Ветка: {branch} ({head.hexsha[:7]}), база: {base}
Изменённые файлы ({len(files)}):
{flist}

## Контекст проекта (RAG)
{context}

## Карточки затронутых объектов метаданных
{cards}

## Diff (base...HEAD)
```diff
{diff}
```
"""


def run_review(base: str, out_file: str | None) -> int:
    config.setup_logging()
    problems = [p for p in config.validate() if "DUMP_ROOT" in p]
    if problems:
        print("ОШИБКА: " + "; ".join(problems), file=sys.stderr)
        return 2
    try:
        repo = _repo()
    except RuntimeError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 2
    try:
        files = changed_files(repo, base)
        if not files:
            log.info("Изменений относительно %s нет — ревью не требуется", base)
            return 0
        diff = diff_text(repo, base)
    except Exception as e:
        print(f"ОШИБКА git (base='{base}'): {e}", file=sys.stderr)
        return 2

    mmap = parser_1c.build_metadata_map(config.DUMP_ROOT)
    objects = map_files_to_objects(files, mmap)
    log.info("Изменённых файлов: %d; затронуто объектов: %d", len(files), len(objects))

    # RAG: индекс и энкодер — опционально (CI строит индекс заранее)
    store, encoder = None, None
    try:
        from indexer.embeddings import get_encoder
        from indexer.store import VectorStore
        store = VectorStore.load(config.DATA_DIR)
        if store is not None:
            encoder = get_encoder()
    except Exception as e:
        log.warning("RAG недоступен: %s", e)
    context = rag_context(store, encoder, {p for _s, p in files})

    if not config.DEEPSEEK_API_KEY:
        print("ОШИБКА: DEEPSEEK_API_KEY не задан — ревью невозможно", file=sys.stderr)
        return 3
    from agent.llm_client import DeepSeekClient
    prompt = build_prompt(base, repo, files, objects, context, diff)
    log.info("Промпт ревью: %d символов; вызов %s", len(prompt), config.DEEPSEEK_MODEL)
    msg = DeepSeekClient().chat([
        {"role": "system", "content": REVIEW_SYSTEM},
        {"role": "user", "content": prompt},
    ])
    review = (msg.content or "").strip()
    header = (f"<!-- ai-review -->\n**AI-ревью** (модель {config.DEEPSEEK_MODEL}, "
              f"base `{base}`, {len(files)} файлов)\n\n")
    text = header + review + "\n"
    if out_file:
        Path(out_file).write_text(text, encoding="utf-8")
        log.info("Ревью записано в %s", out_file)
    else:
        print(text)
    return 0


def cli() -> None:
    ap = argparse.ArgumentParser(description="AI-ревью изменений (PR) конфигурации 1С")
    ap.add_argument("--base", default=os.getenv("GITHUB_BASE_REF", "main"),
                    help="базовая ветка/коммит (по умолчанию $GITHUB_BASE_REF или 'main')")
    ap.add_argument("--out", default="", help="куда записать markdown (по умолчанию stdout)")
    args = ap.parse_args()
    base = args.base
    # в CI base приходит как 'main', а ref лежит в origin/
    try:
        repo = _repo()
        if base and not base.startswith("origin/"):
            local = {b.name for b in repo.branches}
            remote = ({r.name for r in repo.remotes.origin.refs}
                      if "origin" in {r.name for r in repo.remotes} else set())
            if base not in local and f"origin/{base}" in remote:
                base = f"origin/{base}"
    except Exception:
        pass  # диагностика ниже в run_review
    sys.exit(run_review(base, args.out or None))


if __name__ == "__main__":
    cli()
