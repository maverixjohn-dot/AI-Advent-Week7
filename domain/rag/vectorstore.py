"""Векторное хранилище на FAISS (IndexFlatIP, косинусная близость
по нормализованным векторам). Персистентность: index.faiss + chunks.json.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np


class VectorStore:
    def __init__(self, directory: str | Path):
        import faiss  # noqa: F401 — проверка наличия при инициализации
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "index.faiss"
        self.meta_path = self.dir / "chunks.json"
        self._lock = threading.Lock()
        self._index = None
        self._chunks: list[dict] = []
        self._load()

    def _load(self) -> None:
        import faiss
        with self._lock:
            if self.index_path.exists():
                self._index = faiss.read_index(str(self.index_path))
            if self.meta_path.exists():
                self._chunks = json.loads(
                    self.meta_path.read_text(encoding="utf-8"))

    def _ensure_index(self, dim: int):
        import faiss
        if self._index is None:
            self._index = faiss.IndexFlatIP(dim)
        elif self._index.d != dim:
            raise ValueError(
                f"Размерность эмбеддингов изменилась ({self._index.d} → {dim}). "
                "Удалите storage/rag и переиндексируйте базу знаний.")

    def count(self) -> int:
        return 0 if self._index is None else self._index.ntotal

    def add(self, vectors: np.ndarray, metas: list[dict]) -> None:
        if len(vectors) == 0:
            return
        with self._lock:
            self._ensure_index(vectors.shape[1])
            self._index.add(vectors)
            self._chunks.extend(metas)

    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[float, dict]]:
        with self._lock:
            if self._index is None or self._index.ntotal == 0:
                return []
            k = min(top_k, self._index.ntotal)
            scores, ids = self._index.search(vector.reshape(1, -1), k)
            out = []
            for score, idx in zip(scores[0], ids[0]):
                if 0 <= idx < len(self._chunks):
                    out.append((float(score), self._chunks[idx]))
            return out

    def clear(self) -> None:
        with self._lock:
            self._index = None
            self._chunks = []
            for p in (self.index_path, self.meta_path):
                if p.exists():
                    p.unlink()

    def save(self) -> None:
        import faiss
        with self._lock:
            if self._index is not None:
                faiss.write_index(self._index, str(self.index_path))
            self.meta_path.write_text(
                json.dumps(self._chunks, ensure_ascii=False), encoding="utf-8")
