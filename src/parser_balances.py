"""Парсер справок об остатках по счетам (Т-Банк и похожие).

Остатки — это «снимок» состояния, а не обороты, поэтому:
  - в LLM они НЕ отправляются вообще (нечего классифицировать);
  - в Excel пишутся перезаписью ячейки, а не дописыванием (см. excel_writer).

Формат справок различается, поэтому парсер толерантный: ищет строки
с ключевыми словами остатка и суммой, а контекст (карта/счёт/вклад)
берёт из ближайшей предыдущей строки. Номера счетов в метке
обрезаются до последних 4 цифр.
"""
import re

import pdfplumber

AMOUNT_RE = re.compile(r"([+-]?\d[\d\s]*[.,]\d{2})\s*₽")
BALANCE_KEYS = {
    "начало": ["остаток на начало", "входящий остаток", "начальный остаток"],
    "конец": ["остаток на конец", "исходящий остаток", "конечный остаток",
              "текущий баланс", "доступно"],
}
ACCOUNT_RE = re.compile(
    r"(сч[её]т|карта|вклад|депозит|накопительн)[^\n]*?(\d{4})\b", re.IGNORECASE)
DATE_ANY_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")


def _to_float(s: str) -> float:
    return float(s.replace(" ", "").replace(" ", "").replace(",", "."))


def _kind_of(line: str) -> str | None:
    low = line.lower()
    for kind, keys in BALANCE_KEYS.items():
        if any(k in low for k in keys):
            return kind
    return None


def parse_balances_pdf(path: str) -> list[dict]:
    """Возвращает [{'label', 'kind': 'начало'|'конец', 'amount', 'raw'}]."""
    found: list[dict] = []
    last_account = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                m_acc = ACCOUNT_RE.search(line)
                if m_acc:
                    last_account = f"{m_acc.group(1).capitalize()} *{m_acc.group(2)}"
                kind = _kind_of(line)
                if not kind:
                    continue
                m_sum = AMOUNT_RE.search(line)
                if not m_sum:
                    continue
                dates = DATE_ANY_RE.findall(line)
                found.append({
                    "label": last_account or "Счёт (не распознан)",
                    "kind": kind,
                    "amount": _to_float(m_sum.group(1)),
                    "as_of": dates[-1] if dates else "",
                    "raw": line[:120],
                })
    if not found:
        raise ValueError(
            "Остатки не найдены. Пришлите скриншот первой страницы справки "
            "(без ФИО) — откалибрую парсер под ваш формат."
        )
    return found
