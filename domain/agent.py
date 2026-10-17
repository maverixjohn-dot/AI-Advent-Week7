"""Агент поддержки пользователей.

Связывает воедино:
- контекст пользователя и тикета (через MCP → CRM),
- RAG (фрагменты базы знаний в промпте),
- вызов LLM DeepSeek с function calling по MCP-инструментам,
- журналирование всех шагов (dialog / rag / mcp / llm / feedback).
"""
from __future__ import annotations

import json
from typing import Any

from data.models import (
    AgentConfig, Dialog, Feedback, new_id, new_message, now_iso,
)
from data.repositories import DialogRepo, FeedbackRepo, AgentConfigRepo
from domain.deepseek_client import DeepSeekClient
from domain.log_service import LogService
from domain.mcp_client import MCPClient
from domain.rag.retriever import Retriever

MAX_TOOL_ITERATIONS = 6

SYSTEM_PROMPT_TEMPLATE = """Ты — ассистент поддержки облачного продукта «Контур.Учёт».
Отвечай на русском, кратко и по делу, без лишних вступлений.

Правила:
1. Опирайся на фрагменты базы знаний, приложенные к сообщению пользователя.
   Если ответа в них нет — честно скажи об этом и предложи зафиксировать
   проблему в тикете (инструмент add_ticket_comment) для оператора.
2. Учитывай контекст пользователя и тикета ниже: версию продукта, тариф,
   окружение, историю обращения.
3. В конце ответа отдельной строкой перечисли источники, на которые опирался:
   «Источники: имя_файла.md». Если база не использовалась — строку не пиши.
4. Не выдумывай факты о продукте, ценах и сроках. Нет данных — так и скажи.
5. Для вопросов о состоянии тикета используй инструменты MCP
   (get_ticket, list_tickets), а не память.

{context}
"""


class SupportAgent:
    def __init__(self, configs: AgentConfigRepo, dialogs: DialogRepo,
                 feedback: FeedbackRepo, llm: DeepSeekClient,
                 mcp: MCPClient, retriever: Retriever,
                 log_service: LogService):
        self.configs = configs
        self.dialogs = dialogs
        self.feedback_repo = feedback
        self.llm = llm
        self.mcp = mcp
        self.retriever = retriever
        self.log = log_service

    # ------------------------------------------------------------------
    # конфиг и контекст
    # ------------------------------------------------------------------

    @property
    def config(self) -> AgentConfig:
        return self.configs.get_or_create_default()

    def _mcp_call(self, name: str, args: dict) -> Any:
        result = self.mcp.call(name, args)
        self.log.log("mcp.call", tool=name, args=args,
                     ok=not (isinstance(result, dict) and "error" in result),
                     result_preview=str(result)[:500])
        return result

    def resolve_context(self, identifier: str) -> dict:
        """Идентификатор (email или номер тикета) → пользователь + тикет."""
        identifier = (identifier or "").strip()
        if not identifier:
            raise ValueError("Введите email или номер тикета")
        if not self.mcp.ping():
            raise ValueError(
                "MCP-сервер CRM недоступен — данные о пользователях и "
                "тикетах получить невозможно. Локально сервер поднимается "
                "автоматически вместе с приложением; если он не стартовал, "
                "запустите вручную: python -m mcp_server.server "
                "(порт 8001) и проверьте, что установлен uvicorn>=0.34.")
        user, ticket = None, None
        if "@" in identifier:
            user = self._mcp_call("find_user", {"email": identifier})
            if isinstance(user, dict) and "error" in user:
                user = None
        else:
            ref = identifier.upper().replace(" ", "")
            if ref.isdigit():            # «1001» → «T-1001»
                ref = f"T-{ref}"
            ticket = self._mcp_call("get_ticket", {"ticket": ref})
            if isinstance(ticket, dict) and "error" in ticket:
                ticket = None
            if ticket:
                user = self._mcp_call("get_user",
                                      {"user_id": ticket.get("user_id", "")})
                if isinstance(user, dict) and "error" in user:
                    user = None
        if user and ticket is None:
            tickets = self._mcp_call("list_tickets", {"user_id": user["id"]})
            if isinstance(tickets, list) and tickets:
                active = [t for t in tickets
                          if t.get("status") in ("open", "in_progress")]
                ticket = active[-1] if active else tickets[-1]
        if user is None:
            raise ValueError(
                f"Не найден пользователь или тикет «{identifier}». "
                "Проверьте email или номер тикета (например, T-1001).")
        return {"user": user, "ticket": ticket}

    def _system_prompt(self, cfg: AgentConfig, user: dict,
                       ticket: dict | None) -> str:
        ctx = {"user": user, "ticket": ticket}
        context = "Контекст (JSON):\n" + json.dumps(ctx, ensure_ascii=False,
                                                    indent=2)
        prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context)
        if cfg.system_prompt_extra.strip():
            prompt += "\nДополнительные инструкции администратора:\n" \
                      + cfg.system_prompt_extra.strip()
        return prompt

    # ------------------------------------------------------------------
    # диалог
    # ------------------------------------------------------------------

    def start_dialog(self, identifier: str) -> tuple[Dialog, dict]:
        ctx = self.resolve_context(identifier)
        user, ticket = ctx["user"], ctx["ticket"]
        title = f"{user.get('name', '—')}"
        if ticket:
            title += f" · {ticket.get('number', '')}"
        dialog = Dialog(
            id=new_id(), user_id=user["id"],
            ticket_id=ticket.get("id", "") if ticket else "",
            title=title)
        self.dialogs.upsert(dialog)
        self.log.log("dialog.start", dialog_id=dialog.id,
                     user_id=user["id"],
                     ticket_id=dialog.ticket_id or None)
        return dialog, ctx

    def get_dialog(self, dialog_id: str) -> Dialog | None:
        return self.dialogs.get(dialog_id)

    def _build_kb_block(self, sources: list[dict]) -> str:
        if not sources:
            return ("\n\n[Фрагменты базы знаний: ничего релевантного "
                    "не найдено]")
        parts = ["\n\nФрагменты базы знаний (релевантность):"]
        for i, s in enumerate(sources, 1):
            parts.append(f"[{i}] Документ «{s['doc']}» ({s['score']}):\n"
                         f"{s['text']}")
        return "\n\n".join(parts)

    def ask(self, dialog_id: str, text: str) -> dict:
        """Обработать сообщение пользователя. Возвращает сообщение
        ассистента (dict) — оно же сохранено в диалоге."""
        dialog = self.dialogs.get(dialog_id)
        if dialog is None:
            raise ValueError(f"Диалог не найден: {dialog_id}")
        if dialog.status != "active":
            raise ValueError("Диалог завершён. Начните новый.")
        cfg = self.config

        user = self._mcp_call("get_user", {"user_id": dialog.user_id})
        if isinstance(user, dict) and "error" in user:
            user = {"id": dialog.user_id}
        ticket = None
        if dialog.ticket_id:
            ticket = self._mcp_call("get_ticket",
                                    {"ticket": dialog.ticket_id})
            if isinstance(ticket, dict) and "error" in ticket:
                ticket = None

        # RAG
        try:
            sources = self.retriever.retrieve(
                text, top_k=cfg.rag_top_k, threshold=cfg.rag_threshold)
        except Exception as e:
            self.log.log("rag.error", error=str(e))
            sources = []

        messages: list[dict[str, Any]] = [
            {"role": "system",
             "content": self._system_prompt(cfg, user, ticket)}]
        for m in dialog.messages[-cfg.history_limit:]:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user",
                         "content": text + self._build_kb_block(sources)})

        try:
            tools = self.mcp.openai_tools()
        except Exception as e:
            self.log.log("mcp.error", error=str(e))
            tools = None

        called_tools: list[str] = []
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0,
                       "total_tokens": 0}
        answer = ""
        iterations = 0
        for iterations in range(1, MAX_TOOL_ITERATIONS + 1):
            resp = self.llm.chat(model=cfg.model, messages=messages,
                                 temperature=cfg.temperature,
                                 max_tokens=cfg.max_tokens,
                                 tools=tools, thinking=cfg.thinking,
                                 reasoning_effort=cfg.reasoning_effort)
            msg = resp.choices[0].message
            if getattr(resp, "usage", None):
                for k in usage_total:
                    usage_total[k] += getattr(resp.usage, k, 0) or 0
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                answer = msg.content or ""
                break
            # сериализуем ход ассистента с tool_calls обратно в историю
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [{
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name,
                                 "arguments": tc.function.arguments},
                } for tc in tool_calls],
            })
            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._mcp_call(tc.function.name, args)
                called_tools.append(tc.function.name)
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False,
                                          default=str)[:4000],
                })
        else:
            answer = ("Не удалось завершить обработку запроса "
                      "(превышен лимит вызовов инструментов).")

        self.dialogs.add_message(dialog_id, new_message("user", text))
        assistant_msg = new_message(
            "assistant", answer,
            sources=[{k: s[k] for k in ("doc", "score")} for s in sources],
            tool_calls=called_tools, usage=usage_total)
        self.dialogs.add_message(dialog_id, assistant_msg)
        self.log.log("llm.answer", dialog_id=dialog_id, model=cfg.model,
                     iterations=iterations, tools=called_tools,
                     usage=usage_total,
                     sources=[s["doc"] for s in sources])
        return assistant_msg

    # ------------------------------------------------------------------
    # завершение и оценка
    # ------------------------------------------------------------------

    def close_dialog(self, dialog_id: str) -> Dialog | None:
        dialog = self.dialogs.close(dialog_id)
        if dialog:
            self.log.log("dialog.close", dialog_id=dialog_id,
                         messages=len(dialog.messages))
        return dialog

    def submit_feedback(self, dialog_id: str, rating: int,
                        comment: str = "") -> Feedback:
        dialog = self.dialogs.get(dialog_id)
        if dialog is None:
            raise ValueError(f"Диалог не найден: {dialog_id}")
        if not 1 <= int(rating) <= 5:
            raise ValueError("Оценка должна быть от 1 до 5")
        fb = Feedback(id=new_id(), dialog_id=dialog_id,
                      user_id=dialog.user_id, rating=int(rating),
                      comment=(comment or "").strip())
        self.feedback_repo.upsert(fb)
        if dialog.status == "active":
            self.close_dialog(dialog_id)
        self.log.log("feedback.submit", dialog_id=dialog_id,
                     rating=fb.rating, has_comment=bool(fb.comment))
        return fb
