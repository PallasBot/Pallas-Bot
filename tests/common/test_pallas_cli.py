from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from pallas.console.cli.commands import sync_cmd
from pallas.console.cli.main import build_parser, main

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


def test_parse_ext_install_upgrade_compatibility_flag():
    parser = build_parser()
    args = parser.parse_args(["ext", "install", "pallas-plugin-protocol", "--upgrade"])
    assert args.upgrade is True


@pytest.mark.asyncio
async def test_run_install_async_upgrade_uses_update_operation(monkeypatch):
    from pallas.console.cli.commands import ext_cmd

    update = AsyncMock(return_value={"message": "更新完成。"})
    monkeypatch.setattr(ext_cmd, "update_official_extension_with_options", update)

    assert await ext_cmd.run_install_async("pallas-plugin-protocol", restart=False, upgrade=True) == 0
    update.assert_awaited_once_with("pallas-plugin-protocol", restart=False)


def test_module_invocation_ext_list_does_not_require_nonebot_init():
    proc = subprocess.run(
        [sys.executable, "-m", "pallas.console.cli.main", "ext", "list"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode in (0, 1)
    assert "NoneBot has not been initialized." not in proc.stderr


def test_main_default_starts_unified(monkeypatch):
    called: dict[str, bool] = {}

    def fake_run_unified(args):
        called["skip_port_sync"] = args.skip_port_sync
        return 0

    monkeypatch.setattr(
        "pallas.console.cli.commands.lifecycle.run_unified",
        fake_run_unified,
    )
    assert main([]) == 0
    assert called["skip_port_sync"] is False


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
        [sys.executable, "-m", "pallas.console.cli", "--version"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "pallas" in proc.stdout
