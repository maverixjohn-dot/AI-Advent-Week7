"""Фабрика классификатора: backend выбирается переменной CLASSIFIER_BACKEND.

  deepseek — DeepSeek API (по умолчанию, нужен DEEPSEEK_API_KEY)
  rules    — офлайн-эвристика без LLM (dry-run, тесты)
  ollama   — локальная модель через Ollama (вариант C, максимум приватности)
"""
import os

from ..categories import fallback_category
from .base import BaseClassifier, ClassificationError
from .rule_based import RuleBasedClassifier


def make_classifier(cats: list[dict], backend: str | None = None,
                    mapping: dict[str, str] | None = None,
                    members: list[str] | None = None) -> BaseClassifier:
    backend = backend or os.environ.get("CLASSIFIER_BACKEND", "deepseek")
    inc = fallback_category(cats, "income")
    exp = fallback_category(cats, "expense")
    if backend == "deepseek":
        from .deepseek import DeepSeekClassifier
        return DeepSeekClassifier(income_fallback=inc, expense_fallback=exp,
                                  mapping=mapping)
    if backend == "rules":
        return RuleBasedClassifier(income_fallback=inc, expense_fallback=exp,
                                   mapping=mapping, members=members)
    if backend == "ollama":
        from .ollama_local import OllamaClassifier
        return OllamaClassifier(income_fallback=inc, expense_fallback=exp)
    raise ValueError(f"Неизвестный CLASSIFIER_BACKEND: {backend}")


__all__ = ["make_classifier", "BaseClassifier", "ClassificationError"]
