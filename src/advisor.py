"""Комментарий финансового аналитика по УЖЕ ПОСЧИТАННЫМ агрегатам.

Инварианты:
  - LLM получает только итоговые суммы по категориям и отклонения план/факт —
    никаких отдельных операций и персональных данных;
  - все числа в комментарии обязаны происходить из переданного JSON;
  - запрещены инвестиционные рекомендации с обещанием доходности;
  - без API-ключа работает rule-based fallback (шаблонные выводы из цифр).
"""
import json
import os


def _facts_block(aggregates: dict, plans: dict) -> str:
    return json.dumps({"агрегаты": aggregates, "план_месяца": plans},
                      ensure_ascii=False, indent=1)


SYSTEM = (
    "Ты — сухой семейный финансовый аналитик. Правила, которые нельзя нарушать:\n"
    "1) Используй ТОЛЬКО числа из переданного JSON. Придумывать суммы запрещено.\n"
    "2) Никаких инвестиционных рекомендаций и обещаний доходности — только расходы/бюджет.\n"
    "3) Формат: 4-7 коротких пунктов. Сначала 2-3 самых крупных категории расходов "
    "с суммами и долями, затем где перерасход против плана, затем 1-2 конкретные "
    "меры экономии с суммами из данных. Без воды и мотивации.\n"
    "4) Если данных мало — скажи об этом прямо."
)


def llm_commentary(aggregates: dict, plans: dict) -> str:
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    model = os.environ.get("DEEPSEEK_MODEL_COMMENT", "deepseek-flash")
    user_msg = "Данные (JSON):\n" + _facts_block(aggregates, plans)
    resp = client.chat.completions.create(
        model=model, temperature=0.3,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )
    from .classifier.deepseek import _audit_dump
    _audit_dump(user_msg, resp.choices[0].message.content)
    return resp.choices[0].message.content.strip()


def rule_commentary(aggregates: dict, plans: dict) -> str:
    """Детерминированный комментарий без LLM — все числа из агрегатов."""
    lines = []
    for month, agg in aggregates.items():
        exp = {k: v for k, v in agg["by_category"].items() if v < 0}
        total = abs(agg["expense_total"]) or 1
        top = sorted(exp.items(), key=lambda x: x[1])[:3]
        lines.append(f"• {month}: расходы {abs(agg['expense_total']):,.0f} ₽, "
                     f"доходы {agg['income_total']:,.0f} ₽, операций {agg['n_transactions']}.")
        for name, v in top:
            lines.append(f"• {name}: {abs(v):,.0f} ₽ ({abs(v)/total:.0%} расходов)")
        for name, v in top:
            plan = plans.get(name)
            if plan and abs(v) > plan:
                lines.append(f"• Перерасход против плана: {name} — "
                             f"факт {abs(v):,.0f} ₽ при плане {plan:,.0f} ₽ (+{abs(v)-plan:,.0f} ₽)")
    lines.append("• Комментарий сформирован без LLM (rule-based). "
                 "Задайте DEEPSEEK_API_KEY для развёрнутого анализа.")
    return "\n".join(lines)


CHAT_SYSTEM = (
    "Ты — финансовый помощник семьи. Тебе дан контекст: агрегаты трат "
    "и доходов по месяцам (JSON).\n"
    "Правила:\n"
    "1) О прошлых тратах говори ТОЛЬКО числами из контекста; придумывать "
    "суммы запрещено. Если данных нет — скажи, что нужно сначала разобрать "
    "выписку.\n"
    "2) На вопросы «куда вложить / как сэкономить» отвечай общими "
    "принципами (подушка безопасности, вклады, ИИС, диверсификация, "
    "сокращение крупных статей), опираясь на структуру расходов из контекста.\n"
    "3) Никогда не обещай доходность и не называй конкретные ценные бумаги "
    "как рекомендацию к покупке. В конце ответов про вложения добавляй: "
    "«Не является индивидуальной инвестиционной рекомендацией».\n"
    "4) Отвечай коротко и по делу, списком до 5 пунктов."
)


def chat(question: str, aggregates: dict, plans: dict,
         history: list[dict]) -> tuple[str, str]:
    """Диалог с помощником. history: [{'role','content'}].
    Возвращает (ответ, режим 'llm'|'rules')."""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        return ("Чат работает только с ключом DeepSeek "
                "(DEEPSEEK_API_KEY). Без LLM доступен только "
                "детерминированный комментарий на вкладке разбора.", "rules")
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    model = os.environ.get("DEEPSEEK_MODEL_COMMENT", "deepseek-flash")
    ctx = _facts_block(aggregates, plans)
    messages = [{"role": "system", "content": CHAT_SYSTEM},
                    {"role": "user", "content": "Контекст моих финансов (JSON):\n" + ctx}]
    messages.extend(history[-10:])               # ограничиваем контекст
    messages.append({"role": "user", "content": question})
    resp = client.chat.completions.create(model=model, temperature=0.4,
                                          messages=messages)
    from .classifier.deepseek import _audit_dump
    _audit_dump(messages[-1]["content"], resp.choices[0].message.content)
    return resp.choices[0].message.content.strip(), "llm"


def comment(aggregates: dict, plans: dict) -> tuple[str, str]:
    """Возвращает (текст, режим: 'llm'|'rules')."""
    if os.environ.get("DEEPSEEK_API_KEY"):
        try:
            return llm_commentary(aggregates, plans), "llm"
        except Exception:
            pass  # сеть/ключ упали — честный fallback, а не молчаливый сбой
    return rule_commentary(aggregates, plans), "rules"
