import pytest

from pallas.core.commands import command_limit_list, command_limit_row, missing_command_declarations


def test_command_limit_row():
    row = command_limit_row("demo.echo", 30)
    assert row == {"id": "demo.echo", "cd_sec": 30}


def test_command_limit_row_rejects_empty_id():
    with pytest.raises(ValueError, match="command_id"):
        command_limit_row("", 0)


def test_command_limit_list():
    rows = command_limit_list(command_limit_row("a", 1), command_limit_row("b", 0))
    assert len(rows) == 2


def test_missing_command_declarations():
    extra = {
        "command_permissions": [{"id": "demo.a", "label": "A", "default": "everyone"}],
        "command_limits": [{"id": "demo.a", "cd_sec": 5}],
    }
    assert missing_command_declarations(extra, command_ids={"demo.a"}) == []
    missing = missing_command_declarations(extra, command_ids={"demo.a", "demo.b"})
    assert "demo.b: command_permissions" in missing
    assert "demo.b: command_limits" in missing
