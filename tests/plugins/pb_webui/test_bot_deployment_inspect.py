from __future__ import annotations

from unittest.mock import patch

from packages.pb_webui.manager import inspect_bot_deployment


def test_inspect_bot_deployment_docker_when_not_git() -> None:
    with patch("subprocess.check_output", side_effect=OSError("no git")):
        info = inspect_bot_deployment()
    assert info["deployment_mode"] == "docker"
    assert info["git_available"] is False


def test_inspect_bot_deployment_release_tag_dirty() -> None:
    def check_output(cmd: list[str], **kwargs: object) -> str:
        if cmd[:3] == ["git", "rev-parse", "--is-inside-work-tree"]:
            return "true\n"
        if cmd[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return "main\n"
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return " M bot.py\n?? local/plugins/foo\n"
        if cmd == ["git", "describe", "--tags", "--exact-match"]:
            return "v1.0.0\n"
        if cmd[:3] == ["git", "rev-parse", "--short"]:
            return "abc1234\n"
        raise AssertionError(cmd)

    with patch("subprocess.check_output", side_effect=check_output):
        info = inspect_bot_deployment()
    assert info["git_available"] is True
    assert info["deployment_mode"] == "release_tag_dirty"
    assert info["dirty_file_count"] == 2
