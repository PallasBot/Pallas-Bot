from __future__ import annotations

from typing import Any

import pytest

from pallas.core.shared.utils.git_mirror import BUILTIN_MIRRORS, mirror_by_id


def _failover_mirrors(*ids: str) -> list[Any]:
    return [mirror_by_id(mid) or BUILTIN_MIRRORS[0] for mid in ids]


@pytest.mark.asyncio
async def test_update_community_plugin_failover_with_mirror_origin(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_install as mod

    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")

    calls: list[list[str]] = []

    async def fake_git(timeout_s: float, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
        calls.append(list(args))
        if args[:2] == ("remote", "get-url"):
            return 0, "https://github.akams.cn/https://github.com/example/demo.git", ""
        if args[:1] == ("fetch",):
            if args[1].startswith("https://github.akams.cn/"):
                return 1, "", "fatal: repository not found"
            return 0, "fetched", ""
        if args[:2] == ("reset", "--hard"):
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(mod, "run_git_command", fake_git)
    monkeypatch.setattr(mod, "local_plugin_installed", lambda _pid: True)
    monkeypatch.setattr(mod, "plugin_install_path", lambda _pid: plugin_dir)
    monkeypatch.setattr(mod, "extra_plugin_dirs_ready", lambda: True)
    monkeypatch.setattr(mod, "bot_lifecycle_available", lambda: True)
    monkeypatch.setattr(
        mod,
        "iter_mirrors_for_failover",
        lambda _scope: _failover_mirrors("github-akams", "gh-proxy-com", "github"),
    )

    result = await mod.update_community_plugin("demo")

    assert result["installed"] is True
    fetch_urls = [args[1] for args in calls if args[0] == "fetch"]
    assert fetch_urls == [
        "https://github.akams.cn/https://github.com/example/demo.git",
        "https://gh-proxy.com/https://github.com/example/demo.git",
    ]
    resets = [args for args in calls if args[:2] == ["reset", "--hard"]]
    assert resets
    assert resets[-1][2] == "FETCH_HEAD"


@pytest.mark.asyncio
async def test_update_community_plugin_non_github_origin_fetches_original(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_install as mod

    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")

    calls: list[list[str]] = []

    async def fake_git(timeout_s: float, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
        calls.append(list(args))
        if args[:2] == ("remote", "get-url"):
            return 0, "https://gitlab.com/example/demo.git", ""
        if args[:1] == ("fetch",):
            return 0, "fetched", ""
        if args[:2] == ("reset", "--hard"):
            return 0, "", ""
        return 0, "", ""

    monkeypatch.setattr(mod, "run_git_command", fake_git)
    monkeypatch.setattr(mod, "local_plugin_installed", lambda _pid: True)
    monkeypatch.setattr(mod, "plugin_install_path", lambda _pid: plugin_dir)
    monkeypatch.setattr(mod, "extra_plugin_dirs_ready", lambda: True)
    monkeypatch.setattr(mod, "bot_lifecycle_available", lambda: True)

    result = await mod.update_community_plugin("demo")

    assert result["installed"] is True
    fetch_urls = [args[1] for args in calls if args[0] == "fetch"]
    assert fetch_urls == ["https://gitlab.com/example/demo.git"]


@pytest.mark.asyncio
async def test_update_community_plugin_raises_when_all_mirrors_fail(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_install as mod
    from pallas.console.webui.community_plugin_install import CommunityPluginInstallError

    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")

    async def fake_git(timeout_s: float, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
        if args[:2] == ("remote", "get-url"):
            return 0, "https://github.akams.cn/https://github.com/example/demo.git", ""
        if args[:1] == ("fetch",):
            return 1, "", "fatal: repository not found"
        return 0, "", ""

    monkeypatch.setattr(mod, "run_git_command", fake_git)
    monkeypatch.setattr(mod, "local_plugin_installed", lambda _pid: True)
    monkeypatch.setattr(mod, "plugin_install_path", lambda _pid: plugin_dir)
    monkeypatch.setattr(
        mod,
        "iter_mirrors_for_failover",
        lambda _scope: _failover_mirrors("github-akams", "gh-proxy-com"),
    )

    with pytest.raises(CommunityPluginInstallError, match="git fetch 失败"):
        await mod.update_community_plugin("demo")
