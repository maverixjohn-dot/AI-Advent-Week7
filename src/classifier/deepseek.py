"""Классификатор через DeepSeek API (OpenAI-совместимый).

Инварианты, проверяемые кодом:
  - температура 0, ответ строго JSON;
  - категория не из таксономии -> заменяется на «Прочее»/«Прочие расходы»,
    операция попадает в self.unmapped (список для ручной проверки);
  - количество ответов != количеству операций -> ClassificationError;
  - в запрос уходят только обезличенные строки (см. masking.py).

Настройка через .env:
  DEEPSEEK_API_KEY=...
  DEEPSEEK_BASE_URL=https://api.deepseek.com
  DEEPSEEK_MODEL_CLASSIFY=deepseek-flash
"""
import json
import os

from .base import BaseClassifier, ClassificationError

BATCH_SIZE = 50


def _audit_dump(prompt: str, response: str):
    """LLM_AUDIT=1 — сохраняет ТОЧНЫЙ запрос и ответ в output/llm_audit_*.json.
    Позволяет глазами проверить, что наружу ушли только обезличенные строки."""
    if os.environ.get("LLM_AUDIT") != "1":
        return
    import datetime as dt
    out_dir = os.path.join(os.path.dirname(__file__), "..", "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    with open(os.path.join(out_dir, f"llm_audit_{stamp}.json"), "w",
              encoding="utf-8") as f:
        json.dump({"request_user_prompt": prompt, "response": response},
                  f, ensure_ascii=False, indent=1)


class DeepSeekClassifier(BaseClassifier):
    name = "deepseek"

    def __init__(self, income_fallback="Прочее", expense_fallback="Прочие расходы",
                 model=None, base_url=None, api_key=None,
                 mapping: dict[str, str] | None = None):
        from openai import OpenAI  # импорт здесь: rule-based режим не требует SDK
        self.client = OpenAI(
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url=base_url or os.environ.get("DEEPSEEK_BASE_URL",
                                                "https://api.deepseek.com"),
        )
        self.model = model or os.environ.get("DEEPSEEK_MODEL_CLASSIFY", "deepseek-flash")
        self.income_fallback = income_fallback
        self.expense_fallback = expense_fallback
        self.mapping = mapping or {}
        self.unmapped: list[int] = []

    def _prompt(self, batch, categories):
        lines = "\n".join(
            f'{it["idx"]}. {it["date"]} | {it["amount"]:.2f} | {it["description"]}'
            for it in batch
        )
        cats = "\n".join(f"- {c}" for c in categories)
        hints = ""
        if self.mapping:
            pairs = "\n".join(f'"{k}" -> {v}' for k, v in self.mapping.items()
                              if v in categories)
            if pairs:
                hints = ("\nИЗВЕСТНЫЕ СООТВЕТСТВИЯ (применяй в первую очередь):\n"
                         + pairs + "\n")
        return (
            "Ты классификатор банковских операций семейного бюджета.\n"
            "Отнеси каждую операцию РОВНО к одной категории из списка ниже. "
            "Другие категории запрещены. Сумма со знаком '-' — расход, '+' — доход.\n\n"
            f"КАТЕГОРИИ:\n{cats}\n{hints}\n"
            f"ОПЕРАЦИИ (id. дата | сумма | описание):\n{lines}\n\n"
            'Ответь строго JSON: {"labels": [{"id": <int>, "category": "<строка из списка>"}, ...]}. '
            "Без пояснений, без markdown."
        )

    def _call(self, batch, categories):
        prompt = self._prompt(batch, categories)
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Отвечай только валидным JSON."},
                {"role": "user", "content": prompt},
            ],
        )
        raw = resp.choices[0].message.content
        _audit_dump(prompt, raw)
        data = json.loads(raw)
        labels = data.get("labels")
        if not isinstance(labels, list):
            raise ClassificationError("deepseek: нет поля 'labels' в ответе")
        return {int(x["id"]): str(x["category"]) for x in labels}

    def classify_batch(self, items, categories, owner=None):
        self.unmapped = []
        result: dict[int, str] = {}
        for start in range(0, len(items), BATCH_SIZE):
            batch = items[start:start + BATCH_SIZE]
            try:
                mapping = self._call(batch, categories)
            except (ClassificationError, json.JSONDecodeError, KeyError):
                mapping = self._call(batch, categories)  # один повтор
            missing = [it["idx"] for it in batch if it["idx"] not in mapping]
            if missing:
                raise ClassificationError(
                    f"deepseek: нет категории для операций {missing[:5]}..."
                )
            result.update(mapping)
        out = []
        for it in items:
            cat = result[it["idx"]]
            if cat not in categories:
                cat = (self.income_fallback if it["amount"] > 0
                       else self.expense_fallback)
                self.unmapped.append(it["idx"])
            out.append(cat)
        return out
