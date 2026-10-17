"""Векторное хранилище: FAISS (IndexFlatIP по нормализованным векторам = косинус)
+ chunks.json (тексты и метаданные) + vectors.npy (для перестроения индекса).

IndexFlatIP не поддерживает удаление — при инкрементальной переиндексации
перестраиваем индекс из vectors.npy; на нашем объёме это миллисекунды.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import faiss
import numpy as np

log = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, dim: int):
        self.dim = dim
        self.chunks: list[dict] = []
        self.vectors = np.zeros((0, dim), dtype=np.float32)
        self._index = faiss.IndexFlatIP(dim)

    # --- файлы ---
    @classmethod
    def load(cls, directory: Path) -> "VectorStore | None":
        meta = directory / "chunks.json"
        vecs = directory / "vectors.npy"
        if not meta.exists() or not vecs.exists():
            return None
        chunks = json.loads(meta.read_text(encoding="utf-8"))
        vectors = np.load(vecs)
        store = cls(vectors.shape[1])
        store.chunks = chunks
        store.vectors = vectors
        store.rebuild()
        log.info("Индекс загружен: %d чанков, dim=%d", len(chunks), store.dim)
        return store

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "chunks.json").write_text(
            json.dumps(self.chunks, ensure_ascii=False, indent=1), encoding="utf-8")
        np.save(directory / "vectors.npy", self.vectors)
        faiss.write_index(self._index, str(directory / "index.faiss"))
        log.info("Индекс сохранён: %d чанков -> %s", len(self.chunks), directory)

    # --- данные ---
    def add(self, vectors: np.ndarray, chunks: list[dict]) -> None:
        assert len(vectors) == len(chunks)
        self.vectors = np.vstack([self.vectors, vectors]) if len(self.vectors) else vectors
        self.chunks.extend(chunks)
        self.rebuild()

    def remove_sources(self, sources: set[str]) -> int:
        """Удалить все чанки указанных источников. Возвращает число удалённых."""
        keep = [i for i, c in enumerate(self.chunks) if c["source"] not in sources]
        removed = len(self.chunks) - len(keep)
        if removed:
            self.chunks = [self.chunks[i] for i in keep]
            self.vectors = self.vectors[keep] if keep else np.zeros((0, self.dim), np.float32)
            self.rebuild()
        return removed

    def rebuild(self) -> None:
        self._index = faiss.IndexFlatIP(self.dim)
        if len(self.vectors):
            self._index.add(self.vectors)

    def search(self, query_vec: np.ndarray, top_k: int = 5) -> list[tuple[dict, float]]:
        if not len(self.vectors):
            return []
        scores, idx = self._index.search(query_vec.reshape(1, -1), min(top_k, len(self.chunks)))
        return [(self.chunks[i], float(s)) for s, i in zip(scores[0], idx[0]) if i >= 0]
