"""Агрегация и инварианты. Все суммы считает код — LLM числа не создаёт.

Инварианты:
  I1. Внутренние переводы между своими счетами — НЕ доход и НЕ расход.
      Определяются кодом по шаблонам описания до вызова LLM.
  I2. Сверка: суммы по категориям + исключённые переводы == сумма выписки.
      Не сошлось -> InvariantError, файл не выдаётся.
  I3. Дедупликация: хэш уже обработанного файла -> отказ (иначе двойной учёт).
"""
import hashlib
import json
import os
import re

import pandas as pd

TRANSFER_PATTERNS = [
    r"перевод себе",
    r"внутренний перевод",
    r"перевод с договора",
    r"перевод на договор",
    r"между своими счетами",
    r"собственный перевод",
]
TRANSFER_RE = re.compile("|".join(TRANSFER_PATTERNS), re.IGNORECASE)

MONTHS_RU = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май",
             6: "Июнь", 7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь",
             11: "Ноябрь", 12: "Декабрь"}


class InvariantError(RuntimeError):
    pass


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class DedupStore:
    """Журнал обработанных файлов (локальный JSON рядом с приложением)."""

    def __init__(self, path: str):
        self.path = path
        self._seen = set()
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self._seen = set(json.load(f))

    def seen(self, digest: str) -> bool:
        return digest in self._seen

    def check(self, digest: str):
        if digest in self._seen:
            raise InvariantError(
                "Эта выписка уже была обработана ранее (хэш совпал). "
                "Повторная загрузка дала бы двойной учёт — отклонено."
            )

    def commit(self, digest: str):
        self._seen.add(digest)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(sorted(self._seen), f)


def split_internal_transfers(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """I1: возвращает (операции для классификации, исключённые переводы)."""
    mask = df["description"].str.contains(TRANSFER_RE)
    return df[~mask].reset_index(drop=True), df[mask].reset_index(drop=True)


def aggregate(df: pd.DataFrame, labels: list[str], cats: list[dict]) -> dict:
    """Суммы по категориям в разрезе месяцев (labels — отдельным списком)."""
    return aggregate_labeled(df.assign(category=labels), cats)


def aggregate_labeled(work: pd.DataFrame, cats: list[dict]) -> dict:
    """Суммы по категориям в разрезе месяцев. I2 — сверка.
    Ожидает DataFrame с колонкой 'category'."""
    work = work.copy()
    work["month"] = work["date"].dt.month
    work["year"] = work["date"].dt.year

    kind_by_name = {c["name"]: c["type"] for c in cats}
    result: dict[str, dict] = {}
    for (year, month), g in work.groupby(["year", "month"]):
        key = f"{MONTHS_RU[month]} {year}"
        by_cat, income_total, expense_total = {}, 0.0, 0.0
        for cat, sub in g.groupby("category")["amount"]:
            s = round(float(sub.sum()), 2)
            by_cat[cat] = s
            kind = kind_by_name[cat]
            if kind == "income":
                income_total += s
            else:
                expense_total += s
        # I2: сверка с исходными суммами месяца (до копеек)
        raw_income = round(float(g.loc[g.amount > 0, "amount"].sum()), 2)
        raw_expense = round(float(g.loc[g.amount < 0, "amount"].sum()), 2)
        if abs(income_total - raw_income) > 0.01 or abs(expense_total - raw_expense) > 0.01:
            raise InvariantError(
                f"Сверка не сошлась за {key}: "
                f"доход {income_total} vs {raw_income}, расход {expense_total} vs {raw_expense}"
            )
        result[key] = {
            "by_category": by_cat,
            "income_total": round(income_total, 2),
            "expense_total": round(expense_total, 2),  # отрицательное
            "n_transactions": len(g),
        }
    return result
