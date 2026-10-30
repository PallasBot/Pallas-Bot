import pytest

from pallas.console.webui.extension_install import (
    ExtensionInstallError,
    official_extension_packages,
    resolve_official_extension_package,
)
from pallas.console.webui.plugin_registry import build_official_extension_rows


def test_official_extension_packages_covers_matrix_repos():
    from pallas.core.platform.bot_runtime.plugin_matrix import OFFICIAL_EXTENSION_REPOS

    assert official_extension_packages() == frozenset(OFFICIAL_EXTENSION_REPOS.keys())


def test_resolve_rejects_unknown_package():
    with pytest.raises(ExtensionInstallError):
        resolve_official_extension_package("pallas-plugin-not-real")


def test_resolve_rejects_retired_protocol_package():
    with pytest.raises(ExtensionInstallError):
        resolve_official_extension_package("pallas-plugin-protocol")


@pytest.mark.asyncio
async def test_uninstall_retired_protocol_package_remains_explicitly_available(monkeypatch):
    from pallas.console.webui import extension_install

    calls: list[tuple[str, ...]] = []

    async def fake_run_uv_command(timeout_s: float, *args: str) -> tuple[int, str, str]:
        calls.append(args)
        return 0, "ok", ""

    monkeypatch.setattr(extension_install, "pip_package_installed", lambda _package: True)
    monkeypatch.setattr(extension_install, "run_uv_command", fake_run_uv_command)

    result = await extension_install.uninstall_official_extension("pallas-plugin-protocol")

    assert calls == [("pip", "uninstall", "pallas-plugin-protocol")]
    assert result["already_removed"] is False


def test_cli_official_list_excludes_retired_protocol_package(monkeypatch, capsys):
    from argparse import Namespace

    from pallas.console.cli.commands import ext_cmd

    monkeypatch.setattr(ext_cmd, "webui_extension_install_enabled", lambda: True)
    monkeypatch.setattr(ext_cmd, "pip_package_installed", lambda _package: False)

    assert ext_cmd.run_list(Namespace()) == 0
    output = capsys.readouterr().out
    assert "pallas-plugin-protocol" not in output
    assert "pallas-plugin-duel" in output


@pytest.mark.parametrize("enabled", [True, False])
def test_build_official_extension_rows_webui_install_flag(monkeypatch, enabled):
    monkeypatch.setattr("pallas.console.webui.plugin_registry.webui_extension_install_enabled", lambda: enabled)
    monkeypatch.setattr("pallas.console.webui.plugin_registry.pip_package_installed", lambda _package: False)

    rows = build_official_extension_rows()
    duel = next(r for r in rows if r["package"] == "pallas-plugin-duel")
    assert isinstance(duel["webui_install"], bool)
    assert isinstance(duel["pip_installed"], bool)
    assert isinstance(duel["can_install"], bool)
    assert isinstance(duel["can_uninstall"], bool)
    assert duel["webui_install"] is enabled


@pytest.mark.asyncio
async def test_install_official_extension_uses_uv_pip_install(monkeypatch):
    from pallas.console.webui import extension_install

    calls: list[tuple[str, ...]] = []

    async def fake_run_uv_command(timeout_s: float, *args: str) -> tuple[int, str, str]:
        calls.append(args)
        return 0, "ok", ""

    monkeypatch.setattr(extension_install, "run_uv_command", fake_run_uv_command)
    monkeypatch.setattr(extension_install, "pip_package_installed", lambda package: len(calls) > 0)

    result = await extension_install.install_official_extension("pallas-plugin-duel")
    assert calls == [("pip", "install", "--upgrade-package", "pallas-plugin-duel", "pallas-plugin-duel")]
    assert result["package"] == "pallas-plugin-duel"


@pytest.mark.asyncio
async def test_update_official_extension_uses_uv_pip_install(monkeypatch):
    from pallas.console.webui import extension_install

    calls: list[tuple[str, ...]] = []

    async def fake_run_uv_command(timeout_s: float, *args: str) -> tuple[int, str, str]:
        calls.append(args)
        return 0, "ok", ""

    monkeypatch.setattr(extension_install, "pip_package_installed", lambda package: True)
    monkeypatch.setattr(extension_install, "run_uv_command", fake_run_uv_command)

    result = await extension_install.update_official_extension("pallas-plugin-duel")
    assert calls == [
        (
            "pip",
            "install",
            "--upgrade-package",
            "pallas-plugin-duel",
            "--reinstall-package",
            "pallas-plugin-duel",
            "pallas-plugin-duel",
        )
    ]
    assert result["package"] == "pallas-plugin-duel"
