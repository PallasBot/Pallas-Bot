from __future__ import annotations

import sys

import pytest

from pallas.core.foundation.config import repo_settings
from pallas.core.foundation.db import backup
from tools.scripts import backup_database, backup_pg


@pytest.mark.parametrize(
    ("script", "function_name"),
    [(backup_database, "run_database_backup"), (backup_pg, "run_postgres_backup")],
)
def test_backup_cli_applies_repo_settings_before_running_backup(monkeypatch, capsys, script, function_name) -> None:
    calls: list[str] = []
    monkeypatch.setattr(repo_settings, "apply_repo_settings_to_environ", lambda: calls.append("settings"))
    monkeypatch.setattr(
        backup,
        function_name,
        lambda **_kwargs: (
            calls.append("backup") or backup.BackupResult(True, "postgres", "custom", "/tmp/backup", message="done")
        ),
    )
    monkeypatch.setattr(sys, "argv", [script.__name__])

    assert script.main() == 0
    assert calls == ["settings", "backup"]
    assert "done" in capsys.readouterr().out
