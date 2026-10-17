"""Индексация базы знаний: чанкинг файлов storage/kb → эмбеддинги → FAISS."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from data.models import KBDocument, new_id
from data.repositories import KBRepo
from domain.rag.chunking import chunk_text
from domain.rag.vectorstore import VectorStore

SUPPORTED_SUFFIXES = (".md", ".txt")


class KnowledgeBase:
    def __init__(self, kb_dir: Path, store: VectorStore, kb_repo: KBRepo,
                 embedder_fn: Callable, log_service=None):
        self.kb_dir = kb_dir
        self.store = store
        self.repo = kb_repo
        self.embedder_fn = embedder_fn
        self.log = log_service

    def _log(self, event: str, **kw):
        if self.log:
            self.log.log(event, **kw)

    def files(self) -> list[Path]:
        if not self.kb_dir.exists():
            return []
        return sorted(p for p in self.kb_dir.iterdir()
                      if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)

    def index_file(self, path: Path) -> KBDocument:
        """Индексирует один файл, обновляет запись в реестре."""
        doc = self.repo.by_filename(path.name) or KBDocument(
            id=new_id(), name=path.stem, filename=path.name)
        try:
            text = path.read_text(encoding="utf-8")
            chunks = chunk_text(text)
            if chunks:
                vectors = self.embedder_fn().encode_passages(chunks)
                metas = [{"doc": path.name, "chunk_index": i, "text": c}
                         for i, c in enumerate(chunks)]
                self.store.add(vectors, metas)
            doc.chunk_count = len(chunks)
            doc.status = "indexed"
            doc.error = ""
        except Exception as e:  # файл с ошибкой не должен ронять индексацию
            doc.chunk_count = 0
            doc.status = "error"
            doc.error = str(e)
            self._log("rag.error", file=path.name, error=str(e))
        self.repo.upsert(doc)
        return doc

    def rebuild(self) -> dict:
        """Полная переиндексация: очистка индекса и обход всех файлов."""
        self._log("rag.rebuild.start")
        self.store.clear()
        stats = {"files": 0, "chunks": 0, "errors": 0}
        for path in self.files():
            doc = self.index_file(path)
            stats["files"] += 1
            stats["chunks"] += doc.chunk_count
            if doc.status == "error":
                stats["errors"] += 1
        self.store.save()
        self._log("rag.rebuild.done", **stats)
        return stats

    def add_text_document(self, name: str, content: str) -> KBDocument:
        """Сохраняет документ, вставленный текстом из админки, и индексирует."""
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "._- ").strip()
        if not safe:
            raise ValueError("Пустое или недопустимое имя документа")
        if not safe.lower().endswith(SUPPORTED_SUFFIXES):
            safe += ".md"
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        path = self.kb_dir / safe
        path.write_text(content, encoding="utf-8")
        doc = self.index_file(path)
        self.store.save()
        self._log("rag.document.added", file=safe, chunks=doc.chunk_count)
        return doc

    def delete_document(self, filename: str) -> None:
        """Удаляет файл и полностью переиндексирует базу
        (FAISS IndexFlatIP не поддерживает удаление векторов)."""
        path = self.kb_dir / filename
        if path.exists():
            path.unlink()
        doc = self.repo.by_filename(filename)
        if doc:
            self.repo.delete(doc.id)
        self.rebuild()
        self._log("rag.document.deleted", file=filename)
