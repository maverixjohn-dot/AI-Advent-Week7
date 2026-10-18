"""Rule-based классификатор — офлайн-заглушка без LLM.

Нужен для: работы без API-ключа, тестов, dry-run.
Ключевые слова — БАЗОВЫЕ имена статей (без суффиксов владельцев);
вариант владельца («<статья> <owner>») подставляется по members.json.
Пользовательский маппинг с листа «Маппинг» шаблона имеет приоритет
над встроенными ключевыми словами.
"""
from .base import BaseClassifier

KEYWORDS = {
    "Супермаркеты, рестораны, фастфуд": [
        "vkusvill", "вкусвилл", "miratorg", "мираторг", "пятёрочка", "пятерочка",
        "перекрёсток", "перекресток", "магнит", "лента", "ашан", "ресторан",
        "кафе", "кофейн", "фастфуд", "kfc", "вкусно и точка", "бургер",
    ],
    "Маркетплейсы: озон, вб и прочие": [
        "ozon", "озон", "wildberries", "вайлдберриз", "wb", "яндекс маркет",
        "market.yandex", "aliexpress", "маркетплейс",
    ],
    "Аптеки": ["аптека", "горздрав", "rigla", "ригла", "samson", "самсон"],
    "Тройка и Такси": ["taxi", "такси", "тройка", "metro", "метро", "yandex go"],
    "Оплата ипотеки обязательный платеж": ["ипотек", "платеж по ипотеке"],
    "Оплата ЖКУ": ["жку", "жкх", "коммуналь", "мосэнерго", "эпд"],
    "ЖД билеты и Авиабилеты": ["ржд", "rzd", "аэрофлот", "авиа", "s7 ", "победа"],
    "Обучение, подписки обуч": ["курс", "обучен", "skillbox", "нетолог"],
    "Медицина: платные приемы, операции, прививки, анализы": [
        "клиника", "медси", "invitro", "инвитро", "гемотест", "стоматолог",
    ],
    "% на остаток и кэшбек": ["кэшбек", "кешбэк", "% на остаток", "процент на остаток"],
    "Доходы от проф. деятельности": ["зарплата", "з/п", "работодател", "расчетный"],
    "% по вкладам": ["% по вклад", "процент по вклад", "начислены проценты"],
    "Дивиденды": ["дивиденд"],
    "Налоговые вычеты": ["налоговый вычет", "фнс"],
}


class RuleBasedClassifier(BaseClassifier):
    name = "rule-based (эвристика, без LLM)"

    def __init__(self, income_fallback="Прочее", expense_fallback="Прочие расходы",
                 mapping: dict[str, str] | None = None,
                 members: list[str] | None = None):
        self.income_fallback = income_fallback
        self.expense_fallback = expense_fallback
        self.mapping = mapping or {}
        self.members = members or []
        self.unmapped: list[int] = []

    def _owner_variant(self, base_name: str, owner: str | None,
                       allowed: list[str]) -> str | None:
        if owner:
            cand = f"{base_name} {owner}"
            if cand in allowed:
                return cand
        return base_name if base_name in allowed else None

    def classify_batch(self, items, categories, owner=None):
        self.unmapped = []
        out = []
        for it in items:
            desc = it["description"].lower()
            hit = None
            # 1) пользовательский маппинг (лист «Маппинг»)
            for kw, cat in self.mapping.items():
                if kw in desc:
                    hit = cat if cat in categories else None
                    break
            # 2) встроенные ключевые слова (базовые имена)
            if hit is None:
                for base, words in KEYWORDS.items():
                    if any(w in desc for w in words):
                        hit = self._owner_variant(base, owner, categories)
                        if hit:
                            break
            if hit is None:
                hit = self.income_fallback if it["amount"] > 0 else self.expense_fallback
                if hit not in categories:
                    hit = categories[0]
                self.unmapped.append(it["idx"])
            out.append(hit)
        return out
