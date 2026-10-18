"""Тесты инвариантов WorkspaceGuard."""
import pytest

from agent.guard import GuardError, WorkspaceGuard


@pytest.fixture()
def guard(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    return WorkspaceGuard(tmp_path)


def test_normal_path_ok(guard, tmp_path):
    p = guard.resolve("docs/readme.md", for_write=True)
    assert p == tmp_path.resolve() / "docs" / "readme.md"


def test_escape_via_dotdot_rejected(guard):
    with pytest.raises(GuardError, match="ИНВАРИАНТ"):
        guard.resolve("../../outside.txt")


def test_escape_via_nested_dotdot_rejected(guard):
    with pytest.raises(GuardError, match="ИНВАРИАНТ"):
        guard.resolve("docs/../../../outside.txt", for_write=True)


def test_absolute_path_rejected(guard):
    with pytest.raises(GuardError, match="ИНВАРИАНТ"):
        guard.resolve("/etc/passwd")


def test_github_write_rejected(guard):
    with pytest.raises(GuardError, match="read-only"):
        guard.resolve(".github/workflows/evil.yml", for_write=True)


def test_github_read_allowed(guard, tmp_path):
    p = guard.resolve(".github/workflows/ci.yml")  # for_write=False
    assert p.is_file()


def test_empty_path_rejected(guard):
    with pytest.raises(GuardError):
        guard.resolve("   ")


def test_nonexistent_root_rejected(tmp_path):
    with pytest.raises(GuardError, match="не существует"):
        WorkspaceGuard(tmp_path / "no_such_dir")
