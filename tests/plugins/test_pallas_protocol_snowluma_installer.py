"""SnowLuma 安装器：资产名与 Release 选择逻辑。"""

from __future__ import annotations

import sys

from src.plugins.pallas_protocol.runtime.snowluma_installer import (
    default_snowluma_asset_name_for_tag,
    pick_snowluma_asset_from_release,
)


def test_default_snowluma_asset_name_for_tag() -> None:
    assert default_snowluma_asset_name_for_tag("v1.6.4") == (
        "SnowLuma-v1.6.4-win-x64.zip" if sys.platform == "win32" else "SnowLuma-v1.6.4-linux-x64.tar.gz"
    )
    assert default_snowluma_asset_name_for_tag("") == ""
    win_name = default_snowluma_asset_name_for_tag("v1.0.0", target_platform="windows-amd64")
    assert win_name == "SnowLuma-v1.0.0-win-x64.zip"
    assert default_snowluma_asset_name_for_tag("v1.0.0", target_platform="linux-amd64") == (
        "SnowLuma-v1.0.0-linux-x64.tar.gz"
    )


def test_pick_snowluma_asset_from_release_sample() -> None:
    release = {
        "assets": [
            {
                "name": "SnowLuma-v1.6.4-win-x64-lite.zip",
                "browser_download_url": "https://github.com/SnowLuma/SnowLuma/releases/download/v1.6.4/x-lite.zip",
            },
            {
                "name": "SnowLuma-v1.6.4-win-x64.zip",
                "browser_download_url": "https://github.com/SnowLuma/SnowLuma/releases/download/v1.6.4/x.zip",
            },
        ],
    }
    name, url = pick_snowluma_asset_from_release(release, target_platform="windows-amd64")
    assert name == "SnowLuma-v1.6.4-win-x64.zip"
    assert "x.zip" in url
    assert pick_snowluma_asset_from_release(release, target_platform="linux-amd64") is None
