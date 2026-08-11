from __future__ import annotations

from packages.pb_webui.config import Config
from packages.pb_webui.manager import DEFAULT_WEBUI_DIST_ZIP_REPO
from pallas.console.cli import update_ops


def test_webui_update_defaults_use_webui_release_repo(monkeypatch) -> None:
    monkeypatch.setattr(update_ops, "merged_repo_settings_upper", dict)

    assert DEFAULT_WEBUI_DIST_ZIP_REPO == "PallasBot/Pallas-Bot-WebUI"
    assert Config().pallas_webui_dist_zip_repo == "PallasBot/Pallas-Bot-WebUI"
    assert update_ops.webui_update_settings_from_repo()["repo"] == "PallasBot/Pallas-Bot-WebUI"


def test_webui_update_legacy_default_repo_is_normalized() -> None:
    config = Config(pallas_webui_dist_zip_repo="PallasBot/Pallas-Bot")

    assert config.pallas_webui_dist_zip_repo == "PallasBot/Pallas-Bot-WebUI"


def test_webui_update_cli_normalizes_legacy_default_repo(monkeypatch) -> None:
    monkeypatch.setattr(
        update_ops,
        "merged_repo_settings_upper",
        lambda: {"PALLAS_WEBUI_DIST_ZIP_REPO": "PallasBot/Pallas-Bot"},
    )

    assert update_ops.webui_update_settings_from_repo()["repo"] == "PallasBot/Pallas-Bot-WebUI"


def test_webui_update_custom_repo_is_preserved() -> None:
    config = Config(pallas_webui_dist_zip_repo="example/custom-webui")

    assert config.pallas_webui_dist_zip_repo == "example/custom-webui"
