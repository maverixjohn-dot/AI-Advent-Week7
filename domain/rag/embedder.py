"""Эмбеддинги intfloat/multilingual-e5-large локально на CPU.

Модель загружается лениво (при первом обращении) и переиспользуется
всеми компонентами через get_embedder(). E5 требует префиксы
«query: » / «passage: » — без них качество заметно падает.
"""
from __future__ import annotations

import os
import threading

import numpy as np

DEFAULT_MODEL = "intfloat/multilingual-e5-large"


class Embedder:
    def __init__(self, model_name: str | None = None):
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name or os.environ.get(
            "EMBED_MODEL", DEFAULT_MODEL)
        # device="cpu": для объёма FAQ (десятки-сотни чанков) GPU не нужен
        self._model = SentenceTransformer(self.model_name, device="cpu")

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(
            [f"query: {t}" for t in texts],
            normalize_embeddings=True, convert_to_numpy=True,
        ).astype("float32")

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(
            [f"passage: {t}" for t in texts],
            normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        ).astype("float32")


_instance: Embedder | None = None
_lock = threading.Lock()


def get_embedder() -> Embedder:
    global _instance
    with _lock:
        if _instance is None:
            _instance = Embedder()
        return _instance
