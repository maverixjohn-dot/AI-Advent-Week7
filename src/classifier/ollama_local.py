"""Локальный классификатор через Ollama — вариант «C» (полная приватность).

ЗАГЛУШКА-ИНТЕРФЕЙС: код рабочий, но в MVP не тестируется.
Требования: установленный Ollama (https://ollama.com), модель вида
  ollama pull qwen2.5:14b
Запуск: OLLAMA_MODEL=qwen2.5:14b CLASSIFIER_BACKEND=ollama

Данные НЕ покидают машину: запросы идут на localhost:11434.
"""
import json
import os

import urllib.request

from .base import BaseClassifier, ClassificationError


class OllamaClassifier(BaseClassifier):
    name = "ollama (локальная модель)"

    def __init__(self, income_fallback="Прочее", expense_fallback="Прочие расходы",
                 model=None, host=None):
        self.model = model or os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.income_fallback = income_fallback
        self.expense_fallback = expense_fallback
        self.unmapped: list[int] = []

    def classify_batch(self, items, categories, owner=None):
        # Переиспользуем тот же промпт, что и DeepSeek — интерфейс единый
        from .deepseek import DeepSeekClassifier
        prompt = DeepSeekClassifier._prompt(self, items, categories)
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }).encode()
        req = urllib.request.Request(f"{self.host}/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.loads(json.loads(r.read())["response"])
        except Exception as e:
            raise ClassificationError(f"ollama: {e}") from e
        labels = {int(x["id"]): str(x["category"]) for x in data.get("labels", [])}
        self.unmapped = []
        out = []
        for it in items:
            cat = labels.get(it["idx"])
            if cat not in categories:
                cat = (self.income_fallback if it["amount"] > 0
                       else self.expense_fallback)
                self.unmapped.append(it["idx"])
            out.append(cat)
        return out
