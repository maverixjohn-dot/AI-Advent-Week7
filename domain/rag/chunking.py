"""Нарезка документов базы знаний на чанки.

Стратегия: разбиение по заголовкам Markdown и абзацам с накоплением
до max_chars и перекрытием overlap между соседними чанками. Заголовок
текущего раздела добавляется в начало чанка — это сохраняет контекст
для эмбеддингов.
"""
from __future__ import annotations


def _split_blocks(text: str) -> list[str]:
    """Разбивает текст на абзацы (пустая строка — разделитель)."""
    blocks: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip():
            buf.append(line)
        elif buf:
            blocks.append("\n".join(buf))
            buf = []
    if buf:
        blocks.append("\n".join(buf))
    return blocks


def _hard_split(block: str, max_chars: int) -> list[str]:
    """Принудительная нарезка слишком длинного абзаца по границам строк."""
    parts, buf = [], ""
    for line in block.splitlines():
        if buf and len(buf) + len(line) + 1 > max_chars:
            parts.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        parts.append(buf)
    # строка длиннее max_chars режется грубо
    out: list[str] = []
    for p in parts:
        while len(p) > max_chars:
            out.append(p[:max_chars])
            p = p[max_chars:]
        out.append(p)
    return out


def chunk_text(text: str, max_chars: int = 700, overlap: int = 120) -> list[str]:
    """Возвращает список чанков документа."""
    chunks: list[str] = []
    heading = ""
    current = ""

    def flush():
        nonlocal current
        current = current.strip()
        if current:
            chunks.append(current)
        current = ""

    for block in _split_blocks(text):
        first_line = block.splitlines()[0].strip() if block.strip() else ""
        is_heading = first_line.startswith("#")

        if is_heading:
            flush()
            heading = first_line.lstrip("#").strip()
            # заголовок сам по себе чанком не становится, пойдёт префиксом
            body = "\n".join(block.splitlines()[1:]).strip()
            if body:
                block = body
            else:
                continue

        if len(block) > max_chars:
            flush()
            for piece in _hard_split(block, max_chars):
                chunks.append((heading + "\n" + piece).strip() if heading else piece)
            current = ""
            continue

        candidate = f"{current}\n\n{block}".strip() if current else block
        if heading and not candidate.startswith(heading):
            candidate_with_head = f"{heading}\n{candidate}"
        else:
            candidate_with_head = candidate

        if len(candidate_with_head) > max_chars and current:
            flush()
            # перекрытие: хвост предыдущего чанка
            tail = chunks[-1][-overlap:].strip() if chunks and overlap else ""
            parts = [p for p in (heading, tail, block) if p]
            current = "\n".join(parts)
        else:
            current = candidate_with_head

    flush()
    return [c for c in chunks if len(c.strip()) >= 20]
