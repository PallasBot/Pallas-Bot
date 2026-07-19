from pallas.core.commands.checklist import missing_command_declarations


def test_missing_command_declarations_extra_none():
    assert missing_command_declarations(None, command_ids={"demo.cmd"}) == [
        "demo.cmd: command_permissions",
        "demo.cmd: command_limits",
    ]


def test_missing_command_declarations_ignores_malformed_rows():
    extra = {
        "command_permissions": ["bad", None, {"id": "demo.cmd", "label": "x", "default": "everyone"}],
        "command_limits": [123, {"id": "demo.cmd", "cd_sec": 1}],
    }
    assert missing_command_declarations(extra, command_ids={"demo.cmd"}) == []


def test_missing_command_declarations_reports_partial():
    extra = {
        "command_permissions": [{"id": "demo.cmd", "label": "x", "default": "everyone"}],
    }
    assert missing_command_declarations(extra, command_ids={"demo.cmd"}) == [
        "demo.cmd: command_limits",
    ]
