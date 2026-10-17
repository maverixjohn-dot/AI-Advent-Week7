"""Сквозные проверки проекта без pytest: python tests/run_tests.py

1. Хранилище и репозитории (users/tickets/comments/status).
2. Чанкинг документов.
3. RAG: индексация демо-FAQ реальной моделью e5-large + поиск.
4. MCP-сервер (подпроцесс, streamable HTTP) + клиент.
5. Агент поддержки с заглушкой LLM: диалог, tool loop, оценка.
6. Импорт UI-модулей (проверка синтаксиса и имён контролов Flet).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Изолированное хранилище для тестов — ДО импорта модулей проекта
TMP = Path(tempfile.mkdtemp(prefix="support_test_"))
os.environ["STORAGE_DIR"] = str(TMP)
os.environ["MCP_PORT"] = "8123"

PASSED, FAILED = [], []


def check(name: str, fn):
    try:
        fn()
        PASSED.append(name)
        print(f"  PASS  {name}")
    except Exception:
        FAILED.append(name)
        print(f"  FAIL  {name}")
        traceback.print_exc()


# ---------------------------------------------------------------- 1
def test_storage_and_repos():
    from data import seeds
    from data.repositories import UserRepo, TicketRepo, DialogRepo, FeedbackRepo
    from data.storage import JsonStore
    from data.models import new_id, new_message

    store = JsonStore(TMP)
    seeds.ensure_seeded(store)

    users = UserRepo(store)
    assert users.count() == 5
    ivan = users.find_by_email("IVAN.petrov@example.com")  # регистр
    assert ivan and ivan.id == "u-ivan"

    tickets = TicketRepo(store)
    t = tickets.get_by_ref("t-1001") or tickets.get_by_ref("T-1001")
    assert t and t.user_id == "u-ivan"
    t2 = tickets.add_comment("T-1001", "assistant", "Проверено на стенде")
    assert t2 and len(t2.comments) == 2
    t3 = tickets.set_status("T-1001", "resolved")
    assert t3 and t3.status == "resolved"
    assert tickets.set_status("T-1001", "open") is not None  # вернули
    try:
        tickets.set_status("T-1001", "bogus")
        raise AssertionError("ожидали ValueError")
    except ValueError:
        pass

    dialogs = DialogRepo(store)
    from data.models import Dialog
    d = Dialog(id=new_id(), user_id="u-ivan", title="Тест")
    dialogs.upsert(d)
    dialogs.add_message(d.id, new_message("user", "привет"))
    got = dialogs.get(d.id)
    assert got and len(got.messages) == 1
    dialogs.close(d.id)
    assert dialogs.get(d.id).status == "closed"

    fb = FeedbackRepo(store)
    from data.models import Feedback
    fb.upsert(Feedback(id=new_id(), dialog_id=d.id, user_id="u-ivan",
                       rating=5, comment="ок"))
    assert fb.average_rating() == 5.0


# ---------------------------------------------------------------- 2
def test_chunking():
    from domain.rag.chunking import chunk_text
    text = Path(PROJECT_ROOT / "storage_never").exists()  # noqa — no-op
    sample = (TMP / ".." / ".." )  # noqa — no-op
    doc = (TMP / "sample.md")
    doc.write_text("""# Заголовок

Первый абзац про авторизацию и ошибки входа в систему.

Второй абзац: сброс пароля и письма со ссылкой.

## Раздел два

Третий абзац про двухфакторную аутентификацию и коды из SMS.

""" + "Длинная строка. " * 200, encoding="utf-8")
    chunks = chunk_text(doc.read_text(encoding="utf-8"),
                        max_chars=300, overlap=60)
    assert len(chunks) >= 3, f"слишком мало чанков: {len(chunks)}"
    assert all(len(c) <= 400 for c in chunks), "чанк сильно больше лимита"
    assert any("авторизац" in c for c in chunks)
    joined = " ".join(chunks)
    assert "двухфакторн" in joined


# ---------------------------------------------------------------- 3
def test_rag_real_model():
    from data import seeds
    from data.repositories import KBRepo
    from data.storage import JsonStore
    from domain.rag.embedder import get_embedder
    from domain.rag.knowledge import KnowledgeBase
    from domain.rag.retriever import Retriever
    from domain.rag.vectorstore import VectorStore

    store = JsonStore(TMP)
    seeds.ensure_seeded(store)
    vs = VectorStore(TMP / "rag")
    kb = KnowledgeBase(seeds.kb_dir(store), vs, KBRepo(store),
                       get_embedder)
    t0 = time.time()
    stats = kb.rebuild()
    print(f"      индексация: {stats} за {time.time()-t0:.1f} c")
    assert stats["files"] >= 5 and stats["chunks"] >= 15
    assert stats["errors"] == 0

    retr = Retriever(vs, get_embedder)
    t0 = time.time()
    hits = retr.retrieve("не работает авторизация, ошибка AUTH-403",
                         top_k=4, threshold=0.4)
    print(f"      поиск за {time.time()-t0:.2f} c: "
          f"{[(h['doc'], h['score']) for h in hits]}")
    assert hits, "ничего не найдено"
    assert hits[0]["doc"] == "auth.md", f"не тот документ: {hits[0]}"

    hits2 = retr.retrieve("не приходят push на андроиде", top_k=3,
                          threshold=0.4)
    assert hits2 and hits2[0]["doc"] == "mobile.md", hits2

    # персистентность: новое хранилище читает индекс с диска
    vs2 = VectorStore(TMP / "rag")
    assert vs2.count() == stats["chunks"]


# ---------------------------------------------------------------- 4
def _wait_mcp(client, attempts=30):
    for _ in range(attempts):
        try:
            if client.ping():
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def test_mcp_server():
    env = dict(os.environ)
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_server.server"],
        cwd=str(PROJECT_ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        from domain.mcp_client import MCPClient
        client = MCPClient(f"http://127.0.0.1:{os.environ['MCP_PORT']}/mcp")
        assert _wait_mcp(client), "MCP-сервер не поднялся за 30 c"

        tools = client.openai_tools()
        names = {t["function"]["name"] for t in tools}
        expected = {"get_user", "find_user", "list_tickets", "get_ticket",
                    "add_ticket_comment", "update_ticket_status",
                    "create_user"}
        assert expected <= names, names

        # создание пользователя
        created = client.call("create_user", {
            "name": "Тест Тестов", "email": "test@example.com",
            "company": "ООО «Тест»", "plan": "pro",
            "product_version": "4.2.1"})
        assert created.get("email") == "test@example.com" and \
            created.get("id"), created
        dup = client.call("create_user", {"name": "Дубль",
                                          "email": "test@example.com"})
        assert "error" in dup, "дубликат email должен отклоняться"
        bad = client.call("create_user", {"name": "Без почты",
                                          "email": "not-an-email"})
        assert "error" in bad

        user = client.call("find_user", {"email": "ivan.petrov@example.com"})
        assert isinstance(user, dict) and user.get("id") == "u-ivan", user

        ticket = client.call("get_ticket", {"ticket": "T-1001"})
        assert ticket.get("number") == "T-1001", ticket

        tickets = client.call("list_tickets", {"user_id": "u-ivan",
                                               "status": "resolved"})
        assert isinstance(tickets, list) and \
            all(t["status"] == "resolved" for t in tickets)

        upd = client.call("add_ticket_comment",
                          {"ticket": "T-1001", "text": "тест mcp",
                           "author": "test"})
        assert upd["comments"][-1]["text"] == "тест mcp"

        err = client.call("get_ticket", {"ticket": "T-9999"})
        assert "error" in err
        client.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------- 5
def test_resolve_context_numbers():
    """Вход по номеру тикета: «1001», «t-1001», «T-1001» — одно и то же."""
    from data.repositories import AgentConfigRepo, DialogRepo, FeedbackRepo, LogRepo
    from data.storage import JsonStore
    from domain.agent import SupportAgent
    from domain.log_service import LogService
    from domain.mcp_client import MCPClient

    store = JsonStore(TMP)
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_server.server"],
        cwd=str(PROJECT_ROOT), env=dict(os.environ),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        mcp = MCPClient(f"http://127.0.0.1:{os.environ['MCP_PORT']}/mcp")
        assert _wait_mcp(client=mcp)
        agent = SupportAgent(AgentConfigRepo(store), DialogRepo(store),
                             FeedbackRepo(store), FakeLLM([]), mcp,
                             None, LogService(LogRepo(store)))  # type: ignore
        for ref in ("T-1001", "t-1001", "1001"):
            ctx = agent.resolve_context(ref)
            assert ctx["ticket"]["number"] == "T-1001", ref
            assert ctx["user"]["id"] == "u-ivan", ref
        # несуществующий тикет — понятная ошибка
        try:
            agent.resolve_context("T-9999")
            raise AssertionError("ожидали ValueError")
        except ValueError as e:
            assert "не найден" in str(e).lower()
        mcp.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------- 6
def _fake_response(content=None, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                            total_tokens=15)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                           usage=usage)


def _fake_tool_call(name, args: dict):
    import json as _json
    return SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name=name, arguments=_json.dumps(args)))


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)

    def chat(self, **kwargs):
        assert self.script, "FakeLLM: сценарий исчерпан"
        return self.script.pop(0)


def test_agent_flow():
    from data import seeds
    from data.repositories import (
        AgentConfigRepo, DialogRepo, FeedbackRepo, KBRepo, LogRepo,
    )
    from data.storage import JsonStore
    from domain.agent import SupportAgent
    from domain.log_service import LogService
    from domain.mcp_client import MCPClient
    from domain.rag.embedder import get_embedder
    from domain.rag.retriever import Retriever
    from domain.rag.vectorstore import VectorStore

    store = JsonStore(TMP)
    seeds.ensure_seeded(store)
    dialogs = DialogRepo(store)
    feedback = FeedbackRepo(store)
    log_service = LogService(LogRepo(store))

    # MCP-сервер снова поднимаем подпроцессом
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_server.server"],
        cwd=str(PROJECT_ROOT), env=dict(os.environ),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        mcp = MCPClient(f"http://127.0.0.1:{os.environ['MCP_PORT']}/mcp")
        assert _wait_mcp(client=mcp)

        retriever = Retriever(VectorStore(TMP / "rag"), get_embedder,
                              log_service)
        fake = FakeLLM([
            # 1-й вызов LLM: просит инструмент get_ticket
            _fake_response(tool_calls=[
                _fake_tool_call("get_ticket", {"ticket": "T-1001"})]),
            # 2-й вызов: финальный ответ
            _fake_response(content="Проблема в отозванной сессии после "
                                   "обновления 4.2.1. Выйдите и войдите "
                                   "заново. Источники: auth.md"),
        ])
        agent = SupportAgent(AgentConfigRepo(store), dialogs, feedback,
                             fake, mcp, retriever, log_service)  # type: ignore

        dialog, context = agent.start_dialog("ivan.petrov@example.com")
        assert context["user"]["id"] == "u-ivan"
        assert context["ticket"]["number"] == "T-1001"  # активный тикет

        msg = agent.ask(dialog.id, "Почему не работает авторизация?")
        assert "4.2.1" in msg["content"]
        assert msg["tool_calls"] == ["get_ticket"]
        assert msg["sources"], "ожидались источники RAG"
        assert msg["sources"][0]["doc"] == "auth.md"
        assert msg["usage"]["total_tokens"] == 30  # 2 вызова по 15

        saved = dialogs.get(dialog.id)
        assert len(saved.messages) == 2

        agent.close_dialog(dialog.id)
        fb = agent.submit_feedback(dialog.id, 4, "быстро и по делу")
        assert fb.rating == 4
        assert feedback.average_rating() is not None

        logs = store.read_jsonl("logs.jsonl")
        events = {r["event"] for r in logs}
        assert {"dialog.start", "mcp.call", "llm.answer",
                "feedback.submit"} <= events, events
        mcp.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------- 6
def test_ui_imports():
    import flet  # noqa
    import main  # noqa — импортирует ui.user_page, ui.admin_page, ui.logs_page
    assert hasattr(main, "main")


if __name__ == "__main__":
    print("== тесты support_assistant ==")
    check("1. хранилище и репозитории", test_storage_and_repos)
    check("2. чанкинг", test_chunking)
    check("3. RAG (e5-large, CPU)", test_rag_real_model)
    check("4. MCP-сервер + клиент + create_user", test_mcp_server)
    check("5. вход по номеру тикета (T-1001 / t-1001 / 1001)",
          test_resolve_context_numbers)
    check("6. агент: диалог, tool loop, оценка", test_agent_flow)
    check("7. импорт UI/main", test_ui_imports)
    print(f"\nитог: {len(PASSED)} пройдено, {len(FAILED)} провалено")
    if FAILED:
        print("провалены:", ", ".join(FAILED))
        sys.exit(1)
