"""Bot git 管理：历史解析与 is_head 标记。"""

from __future__ import annotations

import pytest

from packages.pb_webui.bot_git_manage import (
    history_item_is_head,
    mark_history_items,
    normalize_bot_git_track_branch,
    normalize_git_apply_mode,
    normalize_git_apply_strategy,
    normalize_git_history_mode,
    parse_commit_history_line,
    parse_release_history_line,
    require_bot_git_track_branch,
)
from packages.pb_webui.manager import BotGitUpdateError, normalize_bot_update_track


def test_normalize_bot_git_track_branch() -> None:
    assert normalize_bot_git_track_branch("dev") == "dev"
    assert normalize_bot_git_track_branch("main") == "main"
    assert normalize_bot_git_track_branch("origin/dev") == "dev"
    assert normalize_bot_git_track_branch("") == "dev"
    assert normalize_bot_git_track_branch("dev_clone") == "dev"
    assert normalize_bot_git_track_branch("feature/x", default="main") == "main"
    assert require_bot_git_track_branch("") == "dev"
    assert require_bot_git_track_branch("main") == "main"
    with pytest.raises(BotGitUpdateError):
        require_bot_git_track_branch("dev_clone")


def test_normalize_git_history_mode() -> None:
    assert normalize_git_history_mode("commit") == "commit"
    assert normalize_git_history_mode("release") == "release"
    assert normalize_git_history_mode("COMMIT") == "commit"
    assert normalize_git_history_mode("") == "commit"
    assert normalize_git_history_mode("other") == "commit"


def test_normalize_git_apply_strategy() -> None:
    assert normalize_git_apply_strategy("safe") == "safe"
    assert normalize_git_apply_strategy("force") == "force"
    assert normalize_git_apply_strategy("FORCE") == "force"
    assert normalize_git_apply_strategy("") == "safe"


def test_normalize_git_apply_mode_alias() -> None:
    assert normalize_git_apply_mode("release") == "release"
    assert normalize_bot_update_track("branch") == "branch"


def test_parse_commit_history_line() -> None:
    parsed = parse_commit_history_line("abc123def456|2026-08-02 12:00:00 +0800|feat: hello")
    assert parsed is not None
    assert parsed["kind"] == "commit"
    assert parsed["ref"] == "abc123def456"
    assert parsed["short_ref"] == "abc123d"
    assert parsed["date"] == "2026-08-02 12:00:00 +0800"
    assert parsed["message"] == "feat: hello"
    assert parse_commit_history_line("bad-line") is None
    assert parse_commit_history_line("") is None


def test_parse_release_history_line() -> None:
    parsed = parse_release_history_line("v3.9.3|2026-08-01 10:00:00 +0800|chore(release): v3.9.3")
    assert parsed is not None
    assert parsed["kind"] == "release"
    assert parsed["ref"] == "v3.9.3"
    assert parsed["short_ref"] == "v3.9.3"
    assert parse_release_history_line("0.6.35|2026-08-01|npm") is None


def test_history_item_is_head_by_tag() -> None:
    item = {"ref": "v3.9.3", "short_ref": "v3.9.3"}
    assert history_item_is_head(item, head_sha="aaa", head_tag="v3.9.3")
    assert not history_item_is_head(item, head_sha="aaa", head_tag="v3.9.0")


def test_history_item_is_head_by_sha() -> None:
    item = {"ref": "abc123def4567890", "short_ref": "abc123def456"}
    assert history_item_is_head(item, head_sha="abc123def4567890abcdef", head_tag="")
    short_item = {"ref": "abc123def456", "short_ref": "abc123def456"}
    assert history_item_is_head(short_item, head_sha="abc123def4567890abcdef", head_tag="")


def test_mark_history_items_flags() -> None:
    items = [
        {"kind": "commit", "ref": "bbb222", "short_ref": "bbb222", "date": "", "message": "newest"},
        {"kind": "commit", "ref": "aaa111", "short_ref": "aaa111", "date": "", "message": "head"},
    ]
    marked = mark_history_items(items, head_sha="aaa111full000000", head_tag="")
    assert marked[0]["is_latest"] is True
    assert marked[0]["is_head"] is False
    assert marked[1]["is_latest"] is False
    assert marked[1]["is_head"] is True

    release_items = [
        {"kind": "release", "ref": "v3.9.3", "short_ref": "v3.9.3", "date": "", "message": ""},
        {"kind": "release", "ref": "v3.9.0", "short_ref": "v3.9.0", "date": "", "message": ""},
    ]
    release_marked = mark_history_items(release_items, head_sha="", head_tag="v3.9.0")
    assert release_marked[0]["is_latest"] is True
    assert release_marked[1]["is_head"] is True
