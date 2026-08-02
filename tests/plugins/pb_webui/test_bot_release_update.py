"""Bot release 更新判定：开发超前 commit 不应提示有更新。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from packages.pb_webui.manager import (
    bot_branch_update_probe,
    bot_has_release_update,
    bot_is_development_build,
    is_bot_release_style_tag,
    normalize_bot_update_track,
    resolve_bot_upstream_ref,
    webui_has_release_update,
)


def test_normalize_bot_update_track() -> None:
    assert normalize_bot_update_track("branch") == "branch"
    assert normalize_bot_update_track("BRANCH") == "branch"
    assert normalize_bot_update_track("release") == "release"
    assert normalize_bot_update_track("") == "release"
    assert normalize_bot_update_track(None) == "release"


def test_same_tag_no_update() -> None:
    assert not bot_has_release_update(latest_tag="v1.0.0", current_tag="v1.0.0")


def test_no_latest_tag() -> None:
    assert not bot_has_release_update(latest_tag="", current_tag="v0.9.0")


@pytest.mark.parametrize(
    ("head_sha", "latest_sha", "ahead_count", "behind_count", "expected"),
    [
        ("aaa", "aaa", 0, 0, False),
        ("bbb", "aaa", 3, 0, False),  # 纯超前：开发构建
        ("aaa", "bbb", 0, 2, True),  # 纯落后：可升级
        ("ccc", "bbb", 190, 5, False),  # 分叉：不误报「有更新」
    ],
)
def test_git_behind_only(
    head_sha: str,
    latest_sha: str,
    ahead_count: int,
    behind_count: int,
    expected: bool,
) -> None:
    root = Path("/fake/repo")

    def check_output(cmd: list[str], **kwargs: object) -> str:
        if cmd[:2] == ["git", "rev-parse"]:
            ref = cmd[2]
            if ref == "HEAD":
                return head_sha + "\n"
            if ref.endswith("^{commit}"):
                return latest_sha + "\n"
        if cmd[:3] == ["git", "rev-list", "--count"]:
            r = cmd[3]
            if r == f"{latest_sha}..{head_sha}":
                return f"{ahead_count}\n"
            if r == f"{head_sha}..{latest_sha}":
                return f"{behind_count}\n"
        raise AssertionError(cmd)

    with (
        patch.object(Path, "exists", return_value=True),
        patch("packages.pb_webui.manager._BOT_ROOT", root),
        patch("subprocess.check_output", side_effect=check_output),
    ):
        assert bot_has_release_update(latest_tag="v1.1.0", current_tag="v1.0.0-dev") is expected


def test_webui_update_ignores_npm_version() -> None:
    assert is_bot_release_style_tag("v3.9.3")
    assert not is_bot_release_style_tag("0.6.35")
    assert not webui_has_release_update(latest_tag="v3.9.3", current_tag="0.6.35")
    assert webui_has_release_update(latest_tag="v3.9.3", current_tag="v3.9.0")
    assert not webui_has_release_update(latest_tag="v3.9.3", current_tag="v3.9.3")


def test_bot_branch_update_probe_behind() -> None:
    root = Path("/fake/repo")

    def check_output(cmd: list[str], **kwargs: object) -> str:
        if cmd[:3] == ["git", "rev-parse", "--abbrev-ref"] and cmd[3] == "@{u}":
            return "origin/dev\n"
        if cmd[:2] == ["git", "rev-parse"]:
            ref = cmd[-1]
            if ref == "HEAD":
                return "aaa111\n"
            if ref == "origin/dev":
                return "bbb222ccccdddd\n"
        if cmd[:3] == ["git", "rev-list", "--count"]:
            if cmd[3] == "aaa111..bbb222ccccdddd":
                return "2\n"
            return "0\n"
        raise AssertionError(cmd)

    with (
        patch("packages.pb_webui.manager._BOT_ROOT", root),
        patch("subprocess.check_output", side_effect=check_output),
    ):
        assert resolve_bot_upstream_ref() == "origin/dev"
        probe = bot_branch_update_probe()
    assert probe["has_update"] is True
    assert probe["commits_behind"] == 2
    assert probe["latest_commit"] == "bbb222ccccdd"
    assert probe["upstream_ref"] == "origin/dev"


def test_bot_branch_update_probe_preferred_branch() -> None:
    root = Path("/fake/repo")

    def check_output(cmd: list[str], **kwargs: object) -> str:
        if cmd[:4] == ["git", "rev-parse", "-q", "--verify"] and cmd[4] == "origin/main":
            return "origin/main\n"
        if cmd[:2] == ["git", "rev-parse"]:
            ref = cmd[-1]
            if ref == "HEAD":
                return "aaa111\n"
            if ref == "origin/main":
                return "aaa111\n"
        if cmd[:3] == ["git", "rev-list", "--count"]:
            return "0\n"
        raise AssertionError(cmd)

    with (
        patch("packages.pb_webui.manager._BOT_ROOT", root),
        patch("subprocess.check_output", side_effect=check_output),
    ):
        probe = bot_branch_update_probe(preferred_branch="main")
    assert probe["has_update"] is False
    assert probe["upstream_ref"] == "origin/main"


@pytest.mark.parametrize(
    ("head_sha", "latest_sha", "ahead_count", "expected"),
    [
        ("bbb", "aaa", 3, True),
        ("aaa", "bbb", 0, False),
        ("aaa", "aaa", 0, False),
    ],
)
def test_development_build_ahead(
    head_sha: str,
    latest_sha: str,
    ahead_count: int,
    expected: bool,
) -> None:
    root = Path("/fake/repo")

    def check_output(cmd: list[str], **kwargs: object) -> str:
        if cmd[:2] == ["git", "rev-parse"]:
            ref = cmd[2]
            if ref == "HEAD":
                return head_sha + "\n"
            if ref.endswith("^{commit}"):
                return latest_sha + "\n"
        if cmd[:3] == ["git", "rev-list", "--count"]:
            r = cmd[3]
            if r == f"{head_sha}..{latest_sha}":
                return "0\n"
            if r == f"{latest_sha}..{head_sha}":
                return f"{ahead_count}\n"
        raise AssertionError(cmd)

    with (
        patch.object(Path, "exists", return_value=True),
        patch("packages.pb_webui.manager._BOT_ROOT", root),
        patch("subprocess.check_output", side_effect=check_output),
    ):
        assert bot_is_development_build(latest_tag="v1.0.0", current_tag="", current_commit="abc1234") is expected
