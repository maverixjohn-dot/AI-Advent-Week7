"""Парсер PDF-справки Т-Банка «Движение средств за период».

Стратегия — текстовая: в реальной справке у таблицы есть только
горизонтальные линии, поэтому поточечное извлечение таблиц pdfplumber
не работает. Операция в тексте выглядит так:

    27.09.2026 27.09.2026 -3 000.00 ₽ -3 000.00 ₽ Внешний перевод по номеру 8010
    15:10 15:10 телефона +7977...

т.е. блок = строка, начинающаяся с даты, + строки-продолжения.

Парсер берёт только строки операций. Шапка справки (ФИО, адрес, счёт)
и колонка «Номер карты» в результат не попадают by design.
"""
import re
import pandas as pd
import pdfplumber

DATE_START_RE = re.compile(r"^(\d{2}\.\d{2}\.\d{4})\s")
PERIOD_RE = re.compile(
    r"Движение средств за период с\s*(\d{2}\.\d{2}\.\d{4})\s*по\s*(\d{2}\.\d{2}\.\d{4})"
)
DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
TIME_RE = re.compile(r"\b\d{2}:\d{2}\b")
AMOUNT_RE = re.compile(r"[+-]?\d[\d\s]*[.,]\d{2}\s*₽")
# Строгая версия для хвоста строки (графа «Доступный остаток»):
# группы тысяч ровно по 3 цифры — иначе «8010 163 700.00 ₽» проглатывается
# как одна сумма вместе с номером карты.
STRICT_AMOUNT_RE = re.compile(r"[+-]?\d{1,3}(?: \d{3})*[.,]\d{2}\s*₽")
# для хвоста строки: сумме не должна предшествовать цифра (защита от
# склейки с номером карты «8010 163 700.00 ₽»)
TRAIL_AMOUNT_RE = re.compile(r"(?<![\d])" + STRICT_AMOUNT_RE.pattern + r"\s*$")
CARD_TAIL_RE = re.compile(r"\s+\d{4}\s*$")
FOOTER_RE = re.compile(r"(АО «ТБанк»|универсальная лицензия|БИК\s|^\s*\d+\s*$)")

# Колонка «Номер карты» — визуально последняя, поэтому в тексте строки
# её значение оказывается последним токеном первой строки операции
# (даже если описание продолжается на следующих строках).
LINE_CARD_TAIL_RE = re.compile(r"\s+\d{4}$")


def _parse_amount(s: str) -> float:
    raw = s.replace("₽", "").replace(" ", "").replace(" ", "").replace(",", ".")
    return float(raw)


def _parse_block(block: str) -> dict | None:
    """Разбирает склеенный текст одной операции."""
    m = DATE_RE.search(block)
    if not m:
        return None
    date = m.group(0)
    amounts = AMOUNT_RE.findall(block)
    if not amounts:
        return None
    # каноническая сумма — «Сумма операции в валюте карты» (вторая)
    amount = _parse_amount(amounts[1] if len(amounts) > 1 else amounts[0])
    desc = block
    desc = desc[m.end():]                    # отрезаем первую дату
    desc = DATE_RE.sub(" ", desc)            # дата списания
    desc = TIME_RE.sub(" ", desc)            # время операции/списания
    desc = AMOUNT_RE.sub(" ", desc)          # обе суммы
    desc = CARD_TAIL_RE.sub("", desc)        # номер карты (хвост)
    desc = re.sub(r"\s+", " ", desc).strip()
    if not desc:
        return None
    return {"date": pd.to_datetime(date, format="%d.%m.%Y"),
            "amount": amount, "description": desc}


def parse_tbank_pdf(path: str) -> tuple[pd.DataFrame, dict]:
    """Возвращает (DataFrame транзакций, мета-информацию справки).

    DataFrame: date (datetime64), amount (float, знак +/-), description (str).
    meta: period, n_rows, balances — если в справке есть графа
    «Доступный остаток», сюда попадает остаток на конец периода по каждой
    карте (в тексте справки операции идут от новых к старым, поэтому
    конец периода — ПЕРВАЯ строка по карте). Хвосты карт используются
    только локально, в DataFrame и дальше не попадают.
    """
    period = None
    blocks: list[tuple[str, str | None, float | None]] = []  # (текст, карта, остаток)
    balance_col = False
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # заголовок «Доступный остаток» pdfplumber рвёт переносами,
            # поэтому проверяем само ключевое слово
            if "Доступный" in text:
                balance_col = True
            for line in text.splitlines():
                line = line.strip()
                if not line or FOOTER_RE.search(line):
                    continue
                if period is None:
                    mp = PERIOD_RE.search(line)
                    if mp:
                        period = (mp.group(1), mp.group(2))
                        continue
                if "Дата списания" in line or "Дата и время" in line:
                    continue  # заголовок таблицы
                if DATE_START_RE.match(line):
                    card, bal = None, None
                    if balance_col:
                        m_bal = TRAIL_AMOUNT_RE.search(line)
                        if m_bal:
                            bal = _parse_amount(m_bal.group(0))
                            line = line[:m_bal.start()].rstrip()
                    m_card = LINE_CARD_TAIL_RE.search(line)
                    if m_card:
                        card = "*" + m_card.group(0).strip()
                        line = LINE_CARD_TAIL_RE.sub("", line)
                    blocks.append((line, card, bal))
                elif blocks and (TIME_RE.match(line) or not DATE_START_RE.match(line)):
                    t, c, b = blocks[-1]
                    blocks[-1] = (t + " " + line, c, b)  # продолжение описания

    rows = [r for (b, _c, _bal) in blocks if (r := _parse_block(b))]
    df = pd.DataFrame(rows, columns=["date", "amount", "description"])
    if df.empty:
        raise ValueError(
            "Транзакции не найдены. Проверьте, что это PDF-справка Т-Банка "
            "«Движение средств» (не скан, не другой банк)."
        )
    df = df.drop_duplicates(subset=["date", "amount", "description"]).reset_index(drop=True)

    balances = []
    seen_cards = set()
    for _t, card, bal in blocks:  # первый встречный = самый новый = конец периода
        if card and bal is not None and card not in seen_cards:
            seen_cards.add(card)
            balances.append({"label": f"Карта {card}", "kind": "конец",
                             "amount": bal,
                             "source": "графа «Доступный остаток»"})
    meta = {"period": period, "n_rows": len(df), "balances": balances}
    return df, meta
