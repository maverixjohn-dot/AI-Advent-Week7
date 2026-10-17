"""Энкодеры эмбеддингов.

Боевой: intfloat/multilingual-e5-large (как в rag-1c), локально, CPU.
Важно: e5 требует префиксов "query: " для запросов и "passage: " для документов —
без них качество поиска заметно деградирует.

Тестовый: HashEncoder — детерминированный псевдо-энкодер без сети и моделей,
только для проверки пайплайна (A1C_EMBED_BACKEND=hash). Смысловой близости не даёт.
"""
from __future__ import annotations

import hashlib
import logging

import numpy as np

import config

log = logging.getLogger(__name__)


class E5Encoder:
    """multilingual-e5-*: префиксы query:/passage:, нормализация, батчи."""

    def __init__(self, model_name: str | None = None, device: str | None = None):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name or config.EMBED_MODEL
        log.info("Загрузка модели эмбеддингов %s (%s)...", self.model_name,
                 device or config.EMBED_DEVICE)
        self._m = SentenceTransformer(self.model_name, device=device or config.EMBED_DEVICE)
        # имя метода переименовано в sentence-transformers 6.x
        getter = getattr(self._m, "get_embedding_dimension", None) \
            or self._m.get_sentence_embedding_dimension
        self.dim = getter()
        log.info("Модель загружена, размерность %d", self.dim)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        v = self._m.encode(["passage: " + t for t in texts],
                           batch_size=config.EMBED_BATCH,
                           normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(v, dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        v = self._m.encode(["query: " + text], normalize_embeddings=True,
                           show_progress_bar=False)
        return np.asarray(v[0], dtype=np.float32)


class HashEncoder:
    """Детерминированный хэш-энкодер для автономных тестов (НЕ для боя)."""

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        words = text.lower().split()
        for i in range(len(words)):
            for n in (1, 2):  # уни- и биграммы
                if i + n <= len(words):
                    token = " ".join(words[i:i + n])
                    h = int(hashlib.md5(token.encode()).hexdigest(), 16)
                    v[h % self.dim] += 1.0 if n == 1 else 0.5
        norm = np.linalg.norm(v)
        return v / norm if norm else v

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts])

    def encode_query(self, text: str) -> np.ndarray:
        return self._vec(text)


_encoder = None


def get_encoder():
    """Ленивый синглтон: модель грузится один раз на процесс."""
    global _encoder
    if _encoder is None:
        _encoder = HashEncoder() if config.EMBED_BACKEND == "hash" else E5Encoder()
    return _encoder
