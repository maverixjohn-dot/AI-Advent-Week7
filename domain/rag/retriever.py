"""Поиск по базе знаний: запрос → эмбеддинг → top-k чанков с порогом."""
from __future__ import annotations

from typing import Callable

from domain.rag.vectorstore import VectorStore


class Retriever:
    def __init__(self, store: VectorStore, embedder_fn: Callable,
                 log_service=None):
        self.store = store
        self.embedder_fn = embedder_fn   # ленивая загрузка модели
        self.log = log_service

    def retrieve(self, query: str, top_k: int = 4,
                 threshold: float = 0.55) -> list[dict]:
        vec = self.embedder_fn().encode_queries([query])[0]
        hits = self.store.search(vec, top_k)
        out = []
        for score, meta in hits:
            if score >= threshold:
                out.append({
                    "doc": meta.get("doc", ""),
                    "chunk_index": meta.get("chunk_index", 0),
                    "score": round(score, 4),
                    "text": meta.get("text", ""),
                })
        if self.log:
            self.log.log("rag.retrieve", query=query, top_k=top_k,
                         threshold=threshold,
                         hits=[{"doc": h["doc"], "score": h["score"]}
                               for h in out])
        return out
