from __future__ import annotations

import asyncio
import importlib.metadata
from pathlib import Path

import pytest


def _write_pyproject(dest: Path, deps: list[str] | None = None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    lines = ["[project]", 'name = "demo"']
    if deps is not None:
        lines.append("dependencies = [")
        lines.extend(f'    "{d}",' for d in deps)
        lines.append("]")
    (dest / "pyproject.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_root_package_with_deps(dest: Path, deps: list[str] | None = None) -> None:
    _write_pyproject(dest, deps)
    (dest / "__init__.py").write_text("", encoding="utf-8")


def _always_missing_version(name: str) -> str:
    raise importlib.metadata.PackageNotFoundError(name)


def test_parse_plugin_dependencies_reads_project_dependencies(tmp_path) -> None:
    from pallas.console.webui.community_plugin_deps import parse_plugin_dependencies

    _write_pyproject(tmp_path, ["httpx>=0.27.0", "qrcode[pil]>=7.4.2"])
    assert parse_plugin_dependencies(tmp_path) == ["httpx>=0.27.0", "qrcode[pil]>=7.4.2"]


def test_parse_plugin_dependencies_missing_pyproject_returns_empty(tmp_path) -> None:
    from pallas.console.webui.community_plugin_deps import parse_plugin_dependencies

    assert parse_plugin_dependencies(tmp_path) == []


def test_parse_plugin_dependencies_no_dependencies_field_returns_empty(tmp_path) -> None:
    from pallas.console.webui.community_plugin_deps import parse_plugin_dependencies

    _write_pyproject(tmp_path, None)
    assert parse_plugin_dependencies(tmp_path) == []


def test_missing_dependencies_filters_satisfied_and_invalid(monkeypatch) -> None:
    from pallas.console.webui.community_plugin_deps import missing_dependencies

    def fake_version(name: str) -> str:
        versions = {"httpx": "0.28.0", "rich": "13.9.0"}
        if name not in versions:
            raise importlib.metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    missing = missing_dependencies(
        ["httpx>=0.27.0", "rich>=13.9.4", "qrcode[pil]>=7.4.2", "bad req!!"]
    )
    assert missing == ["rich>=13.9.4", "qrcode[pil]>=7.4.2"]


@pytest.mark.asyncio
async def test_install_community_plugin_installs_missing_deps(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_deps as deps_mod
    from pallas.console.webui import community_plugin_install as mod

    dest = tmp_path / "skland"

    async def fake_git(timeout_s: float, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
        if args[0] == "clone":
            await asyncio.to_thread(_make_root_package_with_deps, Path(args[-1]), ["httpx>=0.27.0"])
            return 0, "", ""
        return 0, "", ""

    async def fake_uv(timeout_s: float, *args: str) -> tuple[int, str, str]:
        return 0, "installed", ""

    monkeypatch.setattr(mod, "run_git_command", fake_git)
    monkeypatch.setattr(mod, "plugin_install_path", lambda _pid: dest)
    monkeypatch.setattr(mod, "community_plugins_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "extra_plugin_dirs_ready", lambda: True)
    monkeypatch.setattr(mod, "bot_lifecycle_available", lambda: True)
    monkeypatch.setattr(deps_mod, "run_uv_command", fake_uv)
    monkeypatch.setattr(importlib.metadata, "version", _always_missing_version)

    result = await mod.install_community_plugin(
        "skland",
        repository_url="https://github.com/PallasBot/pallas-plugin-skland",
    )

    assert result["installed"] is True
    assert result["deps_installed"] == ["httpx>=0.27.0"]
    assert result["deps_missing"] == []
    assert dest.exists()


@pytest.mark.asyncio
async def test_install_community_plugin_deps_failure_rolls_back(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_deps as deps_mod
    from pallas.console.webui import community_plugin_install as mod
    from pallas.console.webui.community_plugin_install import CommunityPluginInstallError

    dest = tmp_path / "skland"

    async def fake_git(timeout_s: float, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
        if args[0] == "clone":
            await asyncio.to_thread(_make_root_package_with_deps, Path(args[-1]), ["httpx>=0.27.0"])
            return 0, "", ""
        return 0, "", ""

    async def fake_uv(timeout_s: float, *args: str) -> tuple[int, str, str]:
        return 1, "", "network error"

    monkeypatch.setattr(mod, "run_git_command", fake_git)
    monkeypatch.setattr(mod, "plugin_install_path", lambda _pid: dest)
    monkeypatch.setattr(mod, "community_plugins_root", lambda: tmp_path)
    monkeypatch.setattr(deps_mod, "run_uv_command", fake_uv)
    monkeypatch.setattr(importlib.metadata, "version", _always_missing_version)

    with pytest.raises(CommunityPluginInstallError, match="依赖安装失败"):
        await mod.install_community_plugin(
            "skland",
            repository_url="https://github.com/PallasBot/pallas-plugin-skland",
        )
    assert not dest.exists()


@pytest.mark.asyncio
async def test_update_community_plugin_deps_failure_keeps_dir(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_deps as deps_mod
    from pallas.console.webui import community_plugin_install as mod
    from pallas.console.webui.community_plugin_install import CommunityPluginInstallError

    dest = tmp_path / "skland"
    _make_root_package_with_deps(dest, ["httpx>=0.27.0"])

    async def fake_git(timeout_s: float, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
        if args[:2] == ("remote", "get-url"):
            return 0, "https://github.com/PallasBot/pallas-plugin-skland.git", ""
        if args[:1] == ("fetch",):
            return 0, "fetched", ""
        if args[:2] == ("reset", "--hard"):
            return 0, "", ""
        return 0, "", ""

    async def fake_uv(timeout_s: float, *args: str) -> tuple[int, str, str]:
        return 1, "", "network error"

    monkeypatch.setattr(mod, "run_git_command", fake_git)
    monkeypatch.setattr(mod, "local_plugin_installed", lambda _pid: True)
    monkeypatch.setattr(mod, "plugin_install_path", lambda _pid: dest)
    monkeypatch.setattr(mod, "community_plugins_root", lambda: tmp_path)
    monkeypatch.setattr(deps_mod, "run_uv_command", fake_uv)
    monkeypatch.setattr(importlib.metadata, "version", _always_missing_version)

    with pytest.raises(CommunityPluginInstallError, match="依赖安装失败"):
        await mod.update_community_plugin("skland")
    assert dest.exists()


def test_check_loaded_plugin_dependencies_warns_on_missing(monkeypatch, tmp_path) -> None:
    from pallas.core.platform.bot_runtime import plugin_deps as deps_mod
    from pallas.core.platform.bot_runtime import plugin_loader as mod

    plugin_dir = tmp_path / "skland"
    plugin_dir.mkdir()

    monkeypatch.setattr(deps_mod, "parse_plugin_dependencies", lambda _d: ["httpx>=0.27.0"])
    monkeypatch.setattr(deps_mod, "missing_dependencies", lambda reqs: ["httpx>=0.27.0"])
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "pallas.core.foundation.startup_report.register_startup_warning",
        lambda key, value: warnings.append((key, value)),
    )

    mod.check_loaded_plugin_dependencies([plugin_dir])

    assert warnings == [("plugin_deps", "skland（httpx>=0.27.0）")]


def test_check_loaded_plugin_dependencies_silent_when_ok(monkeypatch, tmp_path) -> None:
    from pallas.core.platform.bot_runtime import plugin_deps as deps_mod
    from pallas.core.platform.bot_runtime import plugin_loader as mod

    plugin_dir = tmp_path / "skland"
    plugin_dir.mkdir()

    monkeypatch.setattr(deps_mod, "parse_plugin_dependencies", lambda _d: ["httpx>=0.27.0"])
    monkeypatch.setattr(deps_mod, "missing_dependencies", lambda reqs: [])
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "pallas.core.foundation.startup_report.register_startup_warning",
        lambda key, value: warnings.append((key, value)),
    )

    mod.check_loaded_plugin_dependencies([plugin_dir])

    assert warnings == []


def test_check_loaded_plugin_dependencies_skips_without_pyproject(monkeypatch, tmp_path) -> None:
    from pallas.core.platform.bot_runtime import plugin_loader as mod

    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "pallas.core.foundation.startup_report.register_startup_warning",
        lambda key, value: warnings.append((key, value)),
    )

    mod.check_loaded_plugin_dependencies([plugin_dir])

    assert warnings == []
