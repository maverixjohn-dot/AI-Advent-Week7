"""Тесты файловых инструментов: запись, подтверждения, журнал README, поиск."""
import pytest

from agent.fs_tools import FileTools
from agent.guard import GuardError, WorkspaceGuard


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.bsl").write_text("Процедура Раз()\nКонецПроцедуры\n", encoding="utf-8")
    (tmp_path / "src" / "b.bsl").write_text("Процедура Два()\nКонецПроцедуры\n", encoding="utf-8")
    return tmp_path


def make_tools(ws, confirm=lambda a, d: True):
    return FileTools(WorkspaceGuard(ws), confirm=confirm)


def test_write_new_file_no_confirm_needed(ws):
    asked = []
    tools = make_tools(ws, confirm=lambda a, d: asked.append(a) or False)
    res = tools.write_file("src/new.bsl", "// новый\n", "новый модуль")
    assert "Создан файл" in res
    assert asked == []  # новый файл — без подтверждения
    assert (ws / "src" / "new.bsl").read_text(encoding="utf-8") == "// новый\n"


def test_changelog_written_to_readme(ws):
    tools = make_tools(ws)
    tools.write_file("src/new.bsl", "x", "добавлен модуль new")
    readme = (ws / "README.md").read_text(encoding="utf-8")
    assert "## Журнал доработок" in readme
    assert "добавлен модуль new" in readme
    assert "src/new.bsl" in readme


def test_changelog_appends_to_existing_readme(ws):
    (ws / "README.md").write_text("# Проект\n\nТекст.\n", encoding="utf-8")
    tools = make_tools(ws)
    tools.write_file("src/1.bsl", "1", "первая")
    tools.write_file("src/2.bsl", "2", "вторая")
    readme = (ws / "README.md").read_text(encoding="utf-8")
    assert readme.index("первая") < readme.index("вторая")
    assert "# Проект" in readme


def test_overwrite_requires_confirmation(ws):
    tools = make_tools(ws, confirm=lambda a, d: False)  # аналитик отказал
    res = tools.write_file("src/a.bsl", "// изменён\n", "правка a")
    assert "ОТКАЗАНО аналитиком" in res
    assert "Процедура Раз" in (ws / "src" / "a.bsl").read_text(encoding="utf-8")


def test_overwrite_with_confirmation_shows_diff(ws):
    seen = {}

    def confirm(action, diff):
        seen["action"] = action
        seen["diff"] = diff
        return True

    tools = make_tools(ws, confirm=confirm)
    res = tools.write_file("src/a.bsl", "Процедура Раз()\n// комментарий\nКонецПроцедуры\n", "комментарий")
    assert "Перезаписан файл" in res
    assert seen["diff"].startswith("--- a/src/a.bsl")
    assert "+++ b/src/a.bsl" in seen["diff"]
    assert "+// комментарий" in seen["diff"]


def test_dry_run_writes_nothing(ws):
    tools = make_tools(ws)
    res = tools.write_file("src/a.bsl", "zzz", "правка", dry_run=True)
    assert "DRY-RUN" in res
    assert "Процедура Раз" in (ws / "src" / "a.bsl").read_text(encoding="utf-8")


def test_append_to_file(ws):
    tools = make_tools(ws)
    res = tools.append_to_file("src/a.bsl", "// хвост\n", "дописка")
    assert "Дописан файл" in res
    assert (ws / "src" / "a.bsl").read_text(encoding="utf-8").endswith("// хвост\n")


def test_write_to_github_rejected(ws):
    (ws / ".github").mkdir()
    tools = make_tools(ws)
    with pytest.raises(GuardError):
        tools.write_file(".github/evil.yml", "x", "попытка")


def test_write_outside_workspace_rejected(ws):
    tools = make_tools(ws)
    with pytest.raises(GuardError):
        tools.write_file("../evil.txt", "x", "попытка")


def test_search_across_multiple_files(ws):
    tools = make_tools(ws)
    res = tools.search_files("Процедура")
    assert "a.bsl" in res and "b.bsl" in res
    assert "Совпадений: 2" in res


def test_search_regex(ws):
    tools = make_tools(ws)
    res = tools.search_files(r"Процедура\s+(Раз|Два)", regex=True)
    assert "Совпадений: 2" in res


def test_read_file_lines(ws):
    tools = make_tools(ws)
    res = tools.read_file("src/a.bsl")
    assert "Процедура Раз" in res
    with pytest.raises(GuardError):
        tools.read_file("src/missing.bsl")


def test_decode_1c_names_in_listing(ws):
    (ws / "Catalogs").mkdir()
    (ws / "Catalogs" / "#U0424#U0438#U043d.xml").write_text("x", encoding="utf-8")
    tools = make_tools(ws)
    res = tools.list_files()
    assert "Фин.xml" in res


# ---------------------------------------------------------- JSONL-журнал
import json

from agent.guard import WorkspaceGuard as _WG  # noqa: E402


def _tools_with_log(ws, log_path, confirm=lambda a, d: True):
    return FileTools(_WG(ws), confirm=confirm, change_log=log_path)


def test_change_log_records_created_overwritten_rejected(ws, tmp_path):
    log_path = tmp_path / "data" / "changes.jsonl"
    tools = _tools_with_log(ws, log_path, confirm=lambda a, d: True)
    tools.write_file("src/new.bsl", "v1", "создание")
    tools.write_file("src/new.bsl", "v2", "перезапись")
    refusing = _tools_with_log(ws, log_path, confirm=lambda a, d: False)
    refusing.write_file("src/a.bsl", "v3", "отклонённая правка")

    records = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()]
    assert [r["action"] for r in records] == ["created", "overwritten", "rejected"]
    assert records[0]["path"] == "src/new.bsl"
    assert records[0]["summary"] == "создание"
    assert "+v2" in records[1]["diff"]
    assert all("ts" in r for r in records)


def test_change_log_appended_action(ws, tmp_path):
    log_path = tmp_path / "changes.jsonl"
    tools = _tools_with_log(ws, log_path)
    tools.append_to_file("src/a.bsl", "// хвост\n", "дописка")
    rec = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["action"] == "appended"


def test_change_log_optional(ws):
    tools = make_tools(ws)  # без change_log — ничего не падает
    tools.write_file("src/x.bsl", "x", "без журнала")
    assert not (ws / "changes.jsonl").exists()


def test_dry_run_not_logged(ws, tmp_path):
    log_path = tmp_path / "changes.jsonl"
    tools = _tools_with_log(ws, log_path)
    tools.write_file("src/a.bsl", "z", "проба", dry_run=True)
    assert not log_path.exists()
