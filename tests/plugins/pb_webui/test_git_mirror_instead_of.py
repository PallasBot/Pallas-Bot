"""Bot git 更新与 WebUI dist 下载的镜像 insteadOf / URL 改写。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.pb_webui.manager import (
    apply_bot_repository_update,
    build_git_argv_with_mirror,
    iter_failover_download_urls,
)
from pallas.core.shared.utils import git_mirror as gm
from pallas.core.shared.utils.git_mirror import BUILTIN_MIRRORS, git_instead_of_args


def test_git_instead_of_args_proxy_mirror():
    proxy = next(m for m in BUILTIN_MIRRORS if m.id == "ghproxy-vip")
    assert git_instead_of_args(proxy) == [
        "-c",
        "url.https://ghproxy.vip/https://github.com/.insteadOf=https://github.com/",
    ]


def test_build_git_argv_with_mirror_prepends_instead_of():
    proxy = next(m for m in BUILTIN_MIRRORS if m.id == "ghproxy-vip")
    assert build_git_argv_with_mirror(proxy, "fetch", "origin", "--tags") == [
        "-c",
        "url.https://ghproxy.vip/https://github.com/.insteadOf=https://github.com/",
        "fetch",
        "origin",
        "--tags",
    ]


def test_build_git_argv_with_mirror_github_is_noop(monkeypatch, tmp_path):
    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    github = next(m for m in BUILTIN_MIRRORS if m.id == "github")
    assert build_git_argv_with_mirror(github, "pull", "--ff-only") == ["pull", "--ff-only"]


def test_iter_failover_download_urls_rewrites_release_asset(monkeypatch, tmp_path):
    monkeypatch.setattr(gm, "repo_webui_settings_path", lambda: tmp_path / "webui.json")
    (tmp_path / "webui.json").write_text(
        '{"env":{},"git_mirror":{"preferred_id":"ghproxy-vip","custom_proxy_prefix":""}}\n',
        encoding="utf-8",
    )
    url = "https://github.com/PallasBot/Pallas-Bot-WebUI/releases/download/v1.0.0/dist.zip"
    urls = list(iter_failover_download_urls(url))
    assert urls[0] == (
        "https://ghproxy.vip/https://github.com/PallasBot/Pallas-Bot-WebUI/releases/download/v1.0.0/dist.zip"
    )
    assert urls[-1] == url
    assert len(urls) == len(set(urls))


@pytest.mark.asyncio
async def test_apply_bot_repository_update_fetch_uses_instead_of(monkeypatch, tmp_path):
    ghproxy_mirror = next(m for m in BUILTIN_MIRRORS if m.id == "ghproxy-vip")

    def fake_iter_mirrors():
        yield ghproxy_mirror

    monkeypatch.setattr("packages.pb_webui.manager.iter_mirrors_for_failover", fake_iter_mirrors)
    monkeypatch.setattr("packages.pb_webui.manager._BOT_ROOT", tmp_path)
    monkeypatch.setattr(
        "packages.pb_webui.manager.fetch_latest_bot_release",
        AsyncMock(return_value={"tag": "v9.9.9", "html_url": "", "body": ""}),
    )
    monkeypatch.setattr(
        "packages.pb_webui.manager.get_bot_current_version",
        lambda: {"tag": "v9.9.9", "commit": "abc1234"},
    )

    git_invocations: list[list[str]] = []

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        git_invocations.append(list(cmd))
        proc = MagicMock()
        if cmd == ("git", "rev-parse", "--is-inside-work-tree"):
            proc.communicate = AsyncMock(return_value=(b"true\n", b""))
            proc.returncode = 0
        elif cmd[-3:] == ("fetch", "origin", "--tags"):
            proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.returncode = 0
        elif cmd[-4:] == ("rev-parse", "-q", "--verify", "v9.9.9^{}"):
            proc.communicate = AsyncMock(return_value=(b"deadbeef\n", b""))
            proc.returncode = 0
        elif cmd[-4:] == ("rev-parse", "-q", "--verify", "refs/tags/v9.9.9"):
            proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.returncode = 0
        else:
            proc.communicate = AsyncMock(return_value=(b"", b"unexpected"))
            proc.returncode = 1
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        return proc

    monkeypatch.setattr("packages.pb_webui.manager.asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    result = await apply_bot_repository_update()

    assert result["tag"] == "v9.9.9"
    fetch_calls = [cmd for cmd in git_invocations if "fetch" in cmd and "origin" in cmd]
    assert len(fetch_calls) == 1
    assert fetch_calls[0][1:3] == [
        "-c",
        "url.https://ghproxy.vip/https://github.com/.insteadOf=https://github.com/",
    ]
