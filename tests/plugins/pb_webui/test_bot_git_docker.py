from unittest.mock import AsyncMock, patch

import pytest

from packages.pb_webui.bot_git_manage import load_bot_git_history_payload


@pytest.mark.asyncio
async def test_docker_release_history_uses_github_releases() -> None:
    releases = [
        {"tag": "v4.2.0", "name": "v4.2.0", "published_at": "2026-08-10T00:00:00Z"},
        {"tag": "v4.1.0", "name": "v4.1.0", "published_at": "2026-08-01T00:00:00Z"},
    ]
    with (
        patch(
            "packages.pb_webui.bot_git_manage.inspect_bot_deployment",
            return_value={
                "deployment_mode": "docker",
                "git_available": False,
                "image_version": "v4.0.0",
                "runtime_version": "v4.1.0",
            },
        ),
        patch(
            "packages.pb_webui.bot_git_manage.fetch_github_releases",
            AsyncMock(return_value=releases),
        ) as fetch,
    ):
        payload = await load_bot_git_history_payload(mode="release", limit=20, github_token="token")

    fetch.assert_awaited_once()
    assert [item["ref"] for item in payload["items"]] == ["v4.2.0", "v4.1.0"]
    assert payload["items"][0]["is_latest"] is True
    assert payload["items"][1]["is_head"] is True


@pytest.mark.asyncio
async def test_docker_commit_history_remains_unavailable() -> None:
    with patch(
        "packages.pb_webui.bot_git_manage.inspect_bot_deployment",
        return_value={"deployment_mode": "docker", "git_available": False},
    ):
        payload = await load_bot_git_history_payload(mode="commit")
    assert payload["items"] == []
