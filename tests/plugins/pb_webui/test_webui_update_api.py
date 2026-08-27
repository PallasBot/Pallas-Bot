from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from packages.pb_webui import update_api
from packages.pb_webui.manager import WebuiReleaseCompatibilityError


def _config() -> object:
    class Config:
        pallas_webui_dist_zip_repo = "PallasBot/Pallas-Bot-WebUI"
        pallas_webui_dist_zip_asset = "dist.zip"
        pallas_protocol_github_token = ""

    return Config()


@pytest.mark.asyncio
async def test_webui_update_check_uses_compatible_release(monkeypatch: pytest.MonkeyPatch) -> None:
    selected = {
        "tag": "v0.9.13",
        "html_url": "https://example.test/releases/v0.9.13",
        "asset_url": "https://example.test/releases/download/v0.9.13/dist.zip",
        "body": "release notes",
        "min_bot_commit": "a" * 40,
        "bot_commit": "f" * 40,
    }
    resolver = AsyncMock(return_value=selected)
    latest = AsyncMock()
    monkeypatch.setattr("packages.pb_webui.manager.resolve_compatible_webui_release", resolver)
    monkeypatch.setattr("packages.pb_webui.manager.fetch_latest_webui_release", latest)
    monkeypatch.setattr(
        "packages.pb_webui.manager.get_installed_webui_version",
        lambda: {"tag": "v0.9.12"},
    )
    notes = AsyncMock(return_value="release notes")
    monkeypatch.setattr(
        "pallas.core.shared.utils.github_release.fetch_release_notes_range",
        notes,
    )

    result = await update_api._load_webui_update_check_payload(_config())

    assert result["latest_tag"] == "v0.9.13"
    assert result["has_update"] is True
    assert result["asset_url"] == selected["asset_url"]
    assert result["min_bot_commit"] == "a" * 40
    assert result["bot_commit"] == "f" * 40
    assert notes.await_args.kwargs["limit"] is None
    resolver.assert_awaited_once_with(
        "PallasBot/Pallas-Bot-WebUI",
        "dist.zip",
        "",
        token="",
    )
    latest.assert_not_awaited()


@pytest.mark.asyncio
async def test_webui_update_check_reports_incompatible_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "packages.pb_webui.manager.resolve_compatible_webui_release",
        AsyncMock(side_effect=WebuiReleaseCompatibilityError("没有兼容版本")),
    )
    monkeypatch.setattr(
        "packages.pb_webui.manager.get_installed_webui_version",
        lambda: {"tag": "v0.9.12"},
    )

    result = await update_api._load_webui_update_check_payload(_config())

    assert result["has_update"] is False
    assert result["latest_tag"] is None
    assert "没有兼容版本" in result["error"]


@pytest.mark.asyncio
async def test_webui_update_check_does_not_compare_npm_version_to_release_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = {
        "tag": "v0.9.13",
        "html_url": "https://example.test/releases/v0.9.13",
        "asset_url": "https://example.test/releases/download/v0.9.13/dist.zip",
        "body": "release notes",
        "min_bot_commit": "a" * 40,
        "bot_commit": "f" * 40,
    }
    monkeypatch.setattr(
        "packages.pb_webui.manager.resolve_compatible_webui_release",
        AsyncMock(return_value=selected),
    )
    monkeypatch.setattr(
        "packages.pb_webui.manager.get_installed_webui_version",
        lambda: {"tag": "0.9.12"},
    )
    monkeypatch.setattr(
        "pallas.core.shared.utils.github_release.fetch_release_notes_range",
        AsyncMock(return_value="release notes"),
    )

    result = await update_api._load_webui_update_check_payload(_config())

    assert result["latest_tag"] == "v0.9.13"
    assert result["has_update"] is False
