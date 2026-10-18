"""Интерфейс классификатора транзакций + общая валидация (инварианты).

Любой бэкенд (DeepSeek / rule-based / Ollama) обязан:
  - вернуть ровно столько категорий, сколько транзакций получил;
  - использовать категории только из закрытого списка таксономии.
Нарушение => ClassificationError, файл пользователю не выдаётся.
"""
from abc import ABC, abstractmethod


class ClassificationError(RuntimeError):
    pass


class BaseClassifier(ABC):
    name = "base"

    @abstractmethod
    def classify_batch(self, items: list[dict], categories: list[str],
                       owner: str | None = None) -> list[str]:
        """items: [{'idx', 'date', 'amount', 'description'}] (обезличенные).
        Возвращает список категорий той же длины."""

    def classify(self, items: list[dict], categories: list[str],
                 owner: str | None = None) -> list[str]:
        result = self.classify_batch(items, categories, owner)
        if len(result) != len(items):
            raise ClassificationError(
                f"{self.name}: вернул {len(result)} категорий на {len(items)} операций"
            )
        unknown = [c for c in result if c not in categories]
        if unknown:
            raise ClassificationError(
                f"{self.name}: категории вне таксономии: {set(unknown)}"
            )
        return result
