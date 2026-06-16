from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.console.cli.commands import sync_cmd
from src.console.cli.main import build_parser, main

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_build_parser_help():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])


def test_main_version():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_main_doctor():
    code = main(["doctor"])
    assert code in (0, 1)


def test_main_ext_list():
    code = main(["ext", "list"])
    assert code in (0, 1)


def test_main_sync_dry(monkeypatch):
    async def fake_sync(**_kwargs):
        return 0

    monkeypatch.setattr(sync_cmd, "run_sync_cli", fake_sync)
    assert main(["sync"]) == 0


def test_main_deploy_apply_dry_run():
    code = main(["deploy", "apply", "shard", "--dry-run"])
    assert code in (0, 1)


def test_parse_update_bot_restart():
    parser = build_parser()
    args = parser.parse_args(["update", "bot", "--restart"])
    assert args.restart is True


def test_parse_maintenance_run():
    parser = build_parser()
    args = parser.parse_args(["maintenance", "run", "--update-bot"])
    assert args.update_bot is True
    assert args.no_restart is False


def test_module_invocation():
    proc = subprocess.run(
        [sys.executable, "-m", "src.console.cli", "--version"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "pallas" in proc.stdout
