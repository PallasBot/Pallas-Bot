"""Bot release 更新判定：开发超前 commit 不应提示有更新。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.plugins.pallas_webui.manager import bot_has_release_update


def test_same_tag_no_update() -> None:
    assert not bot_has_release_update(latest_tag="v1.0.0", current_tag="v1.0.0")


def test_no_latest_tag() -> None:
    assert not bot_has_release_update(latest_tag="", current_tag="v0.9.0")


@pytest.mark.parametrize(
    ("head_sha", "latest_sha", "behind_count", "expected"),
    [
        ("aaa", "aaa", 0, False),
        ("bbb", "aaa", 0, False),
        ("aaa", "bbb", 2, True),
    ],
)
def test_git_behind_only(
    head_sha: str,
    latest_sha: str,
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
            assert cmd[3] == f"{head_sha}..{latest_sha}"
            return f"{behind_count}\n"
        raise AssertionError(cmd)

    with (
        patch.object(Path, "exists", return_value=True),
        patch("src.plugins.pallas_webui.manager._BOT_ROOT", root),
        patch("subprocess.check_output", side_effect=check_output),
    ):
        assert (
            bot_has_release_update(latest_tag="v1.1.0", current_tag="v1.0.0-dev")
            is expected
        )
