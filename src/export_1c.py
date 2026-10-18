"""Экспорт итогов в JSON для загрузки в самописную базу 1С «Целеполагание».

Вариант D интеграции (файловый обмен): наш пайплайн пишет
output/1c_export_<год-месяц>.json, обработка 1С «ЗагрузкаБанковскойВыписки»
(код — 1c/Module_ЗагрузкаФинФакта.bsl) читает файл и создаёт документ
«ФинансовыйФакт» с табличной частью СтатьиДоходовИРасходов
(колонки: Показатель, Сумма, Валюта — проверено по выгрузке LifeProgect.zip).

Включается: EXPORT_1C=1
"""
import datetime as dt
import json
import os

from .aggregator import MONTHS_RU

GROUP_BY_TYPE = {"income": "Доходы", "expense": "Расходы"}


def month_key_to_date(month_key: str) -> str:
    """'Сентябрь 2026' -> '2026-09-30' (документ ставим на конец месяца)."""
    name, year = month_key.split()
    month = {v: k for k, v in MONTHS_RU.items()}[name]
    if month == 12:
        last = dt.date(int(year), 12, 31)
    else:
        last = dt.date(int(year), month + 1, 1) - dt.timedelta(days=1)
    return last.isoformat()


def export_month(month_key: str, agg: dict, cats: list[dict],
                 out_dir: str) -> str:
    kind_by_name = {c["name"]: c["type"] for c in cats}
    items = []
    for name, value in agg["by_category"].items():
        kind = kind_by_name[name]
        items.append({
            "group": GROUP_BY_TYPE[kind],
            "article": name,
            "amount": round(abs(value), 2),
            "currency": "RUB",
        })
    payload = {
        "source": "finassistent",
        "period": month_key_to_date(month_key),
        "items": sorted(items, key=lambda x: x["group"]),
    }
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"1c_export_{month_key.replace(' ', '_')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path
