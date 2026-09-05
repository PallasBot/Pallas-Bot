from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


def _make_subdir_package(dest: Path, module: str = "nonebot_plugin_skland") -> None:
    """构造「子目录插件包」仓库：根目录无 __init__.py，插件包在子目录。"""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "pyproject.toml").write_text(
        f'[tool.nonebot]\nplugins = ["{module}"]\n',
        encoding="utf-8",
    )
    sub = dest / module
    sub.mkdir()
    (sub / "__init__.py").write_text("", encoding="utf-8")


def _make_root_package(dest: Path) -> None:
    """构造「根目录即插件包」仓库。"""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "__init__.py").write_text("", encoding="utf-8")


def _make_no_package(dest: Path) -> None:
    """构造无插件包的仓库。"""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "README.md").write_text("", encoding="utf-8")


def _write_meta(root: Path, plugin_id: str, meta: dict) -> None:
    meta_dir = root / ".pallas-install"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / f"{plugin_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_install_community_plugin_promotes_subdir_package(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_install as mod

    dest = tmp_path / "skland"

    async def fake_git(timeout_s: float, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
        if args[0] == "clone":
            await asyncio.to_thread(_make_subdir_package, Path(args[-1]))
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(mod, "run_git_command", fake_git)
    monkeypatch.setattr(mod, "plugin_install_path", lambda _pid: dest)
    monkeypatch.setattr(mod, "community_plugins_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "extra_plugin_dirs_ready", lambda: True)
    monkeypatch.setattr(mod, "bot_lifecycle_available", lambda: True)

    result = await mod.install_community_plugin(
        "skland",
        repository_url="https://github.com/PallasBot/pallas-plugin-skland",
    )

    assert result["installed"] is True
    assert (dest / "__init__.py").is_file()
    assert not (dest / "nonebot_plugin_skland").exists()
    meta = json.loads((tmp_path / ".pallas-install" / "skland.json").read_text(encoding="utf-8"))
    assert meta["layout"] == "subdir"
    assert meta["subdir"] == "nonebot_plugin_skland"


@pytest.mark.asyncio
async def test_install_community_plugin_root_package_unchanged(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_install as mod

    dest = tmp_path / "demo"

    async def fake_git(timeout_s: float, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
        if args[0] == "clone":
            await asyncio.to_thread(_make_root_package, Path(args[-1]))
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(mod, "run_git_command", fake_git)
    monkeypatch.setattr(mod, "plugin_install_path", lambda _pid: dest)
    monkeypatch.setattr(mod, "community_plugins_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "extra_plugin_dirs_ready", lambda: True)
    monkeypatch.setattr(mod, "bot_lifecycle_available", lambda: True)

    result = await mod.install_community_plugin(
        "demo",
        repository_url="https://github.com/example/demo",
    )

    assert result["installed"] is True
    assert (dest / "__init__.py").is_file()
    assert not (tmp_path / ".pallas-install" / "demo.json").exists()


@pytest.mark.asyncio
async def test_install_community_plugin_no_package_raises(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_install as mod
    from pallas.console.webui.community_plugin_install import CommunityPluginInstallError

    dest = tmp_path / "demo"

    async def fake_git(timeout_s: float, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
        if args[0] == "clone":
            await asyncio.to_thread(_make_no_package, Path(args[-1]))
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(mod, "run_git_command", fake_git)
    monkeypatch.setattr(mod, "plugin_install_path", lambda _pid: dest)
    monkeypatch.setattr(mod, "community_plugins_root", lambda: tmp_path)

    with pytest.raises(CommunityPluginInstallError, match="不是有效 NoneBot 插件包"):
        await mod.install_community_plugin(
            "demo",
            repository_url="https://github.com/example/demo",
        )
    assert not dest.exists()


@pytest.mark.asyncio
async def test_update_community_plugin_repromotes_subdir_package(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_install as mod

    dest = tmp_path / "skland"
    # 模拟已安装的提升布局：仓库壳内子目录（reset 后状态）+ 根目录提升残留 + 元数据
    _make_subdir_package(dest)
    (dest / "__init__.py").write_text("", encoding="utf-8")
    _write_meta(tmp_path, "skland", {"layout": "subdir", "subdir": "nonebot_plugin_skland", "plugin_id": "skland"})

    calls: list[list[str]] = []

    async def fake_git(timeout_s: float, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
        calls.append(list(args))
        if args[:2] == ("remote", "get-url"):
            return 0, "https://github.com/PallasBot/pallas-plugin-skland.git", ""
        if args[:1] == ("fetch",):
            return 0, "fetched", ""
        if args[:2] == ("reset", "--hard"):
            return 0, "", ""
        if args[:2] == ("clean", "-fdx"):
            # 模拟 git clean 删除提升残留（未跟踪的根目录 __init__.py）
            (dest / "__init__.py").unlink(missing_ok=True)
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(mod, "run_git_command", fake_git)
    monkeypatch.setattr(mod, "local_plugin_installed", lambda _pid: True)
    monkeypatch.setattr(mod, "plugin_install_path", lambda _pid: dest)
    monkeypatch.setattr(mod, "community_plugins_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "extra_plugin_dirs_ready", lambda: True)
    monkeypatch.setattr(mod, "bot_lifecycle_available", lambda: True)

    result = await mod.update_community_plugin("skland")

    assert result["installed"] is True
    assert (dest / "__init__.py").is_file()
    assert not (dest / "nonebot_plugin_skland").exists()
    assert ["clean", "-fdx"] in calls


@pytest.mark.asyncio
async def test_uninstall_community_plugin_clears_meta(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_install as mod

    dest = tmp_path / "skland"
    dest.mkdir()
    (dest / "__init__.py").write_text("", encoding="utf-8")
    _write_meta(tmp_path, "skland", {"layout": "subdir", "subdir": "nonebot_plugin_skland"})

    monkeypatch.setattr(mod, "plugin_install_path", lambda _pid: dest)
    monkeypatch.setattr(mod, "community_plugins_root", lambda: tmp_path)

    result = await mod.uninstall_community_plugin("skland")

    assert result["installed"] is False
    assert not dest.exists()
    assert not (tmp_path / ".pallas-install" / "skland.json").exists()
