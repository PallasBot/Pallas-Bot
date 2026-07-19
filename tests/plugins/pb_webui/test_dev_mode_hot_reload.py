from unittest.mock import patch

from packages.pb_webui.config import Config, on_pallas_webui_config_reload
from packages.pb_webui.console_meta_store import _CONSOLE_EXTRA, patch_console_meta


def test_patch_console_meta_merges_without_clearing() -> None:
    backup = dict(_CONSOLE_EXTRA)
    try:
        _CONSOLE_EXTRA.clear()
        _CONSOLE_EXTRA.update({"static_root": "/tmp/public", "http_base": "/pallas"})
        patch_console_meta(pallas_webui_dev_mode=True)
        assert _CONSOLE_EXTRA["static_root"] == "/tmp/public"
        assert _CONSOLE_EXTRA["pallas_webui_dev_mode"] is True
    finally:
        _CONSOLE_EXTRA.clear()
        _CONSOLE_EXTRA.update(backup)


def test_on_pallas_webui_config_reload_updates_console_meta() -> None:
    backup = dict(_CONSOLE_EXTRA)
    try:
        _CONSOLE_EXTRA.clear()
        with patch("nonebot.logger") as mock_logger:
            on_pallas_webui_config_reload(Config(pallas_webui_dev_mode=True))
            assert _CONSOLE_EXTRA.get("pallas_webui_dev_mode") is True
            mock_logger.warning.assert_called_once()
            on_pallas_webui_config_reload(Config(pallas_webui_dev_mode=False))
            assert _CONSOLE_EXTRA.get("pallas_webui_dev_mode") is False
            mock_logger.info.assert_called_once()
    finally:
        _CONSOLE_EXTRA.clear()
        _CONSOLE_EXTRA.update(backup)
