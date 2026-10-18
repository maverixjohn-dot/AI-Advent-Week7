"""Тесты агентского цикла с моком LLM (без API-ключа)."""
import pytest

from agent.assistant import CodeAssistant
from agent.fs_tools import FileTools
from agent.guard import WorkspaceGuard
from agent.mock_llm import MockLLM, text_step, tool_step


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.bsl").write_text(
        "// Модуль\nФинансовыеПоказатели.Найти();\n", encoding="utf-8")
    return tmp_path


def make_assistant(ws, script, **kw):
    tools = FileTools(WorkspaceGuard(ws), confirm=kw.pop("confirm", lambda a, d: True))
    mock = MockLLM(script)
    assistant = CodeAssistant(tools, llm=mock, ask=kw.pop("ask", lambda q: "ок"))
    return assistant, mock


def test_full_scenario_search_and_document(ws):
    script = [
        tool_step([("search_files", {"query": "ФинансовыеПоказатели"})]),
        tool_step([("write_file", {"path": "docs/usage.md",
                                   "content": "# Использование\n",
                                   "change_summary": "документация по использованию"})]),
        text_step("Готово: найдено и задокументировано."),
    ]
    assistant, mock = make_assistant(ws, script)
    answer = assistant.run_task("Найди использования и задокументируй")
    assert answer == "Готово: найдено и задокументировано."
    assert (ws / "docs" / "usage.md").exists()
    assert "документация по использованию" in (ws / "README.md").read_text(encoding="utf-8")
    assert [n for n, _ in mock.calls_log] == ["search_files", "write_file"]


def test_invariant_violation_returned_to_model(ws):
    script = [
        tool_step([("write_file", {"path": "../evil.txt", "content": "x",
                                   "change_summary": "попытка"})]),
        text_step("Понял, выход за workspace запрещён."),
    ]
    assistant, mock = make_assistant(ws, script)
    answer = assistant.run_task("Попробуй записать вне workspace")
    assert not (ws.parent / "evil.txt").exists()
    # модель получила отказ инструмента и ответила текстом
    assert "запрещ" in answer.lower()


def test_github_write_blocked_in_loop(ws):
    (ws / ".github").mkdir()
    script = [
        tool_step([("write_file", {"path": ".github/x.yml", "content": "x",
                                   "change_summary": "попытка"})]),
        text_step("Отказано: .github read-only."),
    ]
    assistant, _ = make_assistant(ws, script)
    assistant.run_task("Запиши workflow")
    assert not (ws / ".github" / "x.yml").exists()


def test_ask_analyst_called(ws):
    asked = []
    script = [
        tool_step([("ask_analyst", {"question": "Точно перезаписать?"})]),
        text_step("Уточнил."),
    ]
    tools = FileTools(WorkspaceGuard(ws), confirm=lambda a, d: True)
    assistant = CodeAssistant(tools, llm=MockLLM(script),
                              ask=lambda q: asked.append(q) or "да")
    assistant.run_task("Спроси меня")
    assert asked == ["Точно перезаписать?"]


def test_on_event_progress(ws):
    events = []
    script = [
        tool_step([("search_files", {"query": "Модуль"})]),
        text_step("Нашёл."),
    ]
    tools = FileTools(WorkspaceGuard(ws), confirm=lambda a, d: True)
    assistant = CodeAssistant(tools, llm=MockLLM(script),
                              on_event=lambda k, p: events.append((k, p)))
    assistant.run_task("Поищи")
    kinds = [k for k, _ in events]
    assert kinds == ["tool_call", "tool_result", "answer"]
    assert events[0][1]["name"] == "search_files"
    assert events[-1][1]["text"] == "Нашёл."


def test_iteration_limit(ws, monkeypatch):
    import config
    monkeypatch.setattr(config, "MAX_ITER", 2)
    script = [tool_step([("list_files", {})])] * 5  # бесконечные вызовы
    assistant, _ = make_assistant(ws, script)
    answer = assistant.run_task("Зациклись")
    assert "лимит итераций" in answer
