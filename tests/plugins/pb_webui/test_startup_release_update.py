from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from packages.pb_webui import startup


@pytest.mark.asyncio
async def test_startup_release_resolution_uses_compatible_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = {
        "tag": "v0.9.13",
        "asset_url": "https://example.test/releases/download/v0.9.13/dist.zip",
    }
    resolver = AsyncMock(return_value=selected)
    latest = AsyncMock(side_effect=AssertionError("启动路径不应直接查询 latest"))
    monkeypatch.setattr(startup, "resolve_compatible_webui_release", resolver)
    monkeypatch.setattr(startup, "fetch_latest_webui_release", latest, raising=False)

    result = await startup.resolve_webui_release_for_runtime(
        "PallasBot/Pallas-Bot",
        "dist.zip",
        "",
        token="token",
    )

    assert result == selected
    resolver.assert_awaited_once_with(
        "PallasBot/Pallas-Bot-WebUI",
        "dist.zip",
        "",
        token="token",
    )
    latest.assert_not_awaited()
