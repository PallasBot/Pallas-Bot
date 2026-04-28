from types import SimpleNamespace
from unittest.mock import patch

from src.plugins.pallas_protocol.config import Config, onebot_connection_hints, resolve_onebot_ws_settings


def test_resolve_onebot_ws_settings_fallback_to_driver_config() -> None:
    cfg = Config()
    fake_driver = SimpleNamespace(config=SimpleNamespace(host="127.0.0.1", port=8080, access_token="abc123"))
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("nonebot.get_driver", return_value=fake_driver),
    ):
        url, name, token = resolve_onebot_ws_settings(cfg)
    assert url == "ws://127.0.0.1:8080/onebot/v11/ws"
    assert name == "pallas"
    assert token == "abc123"


def test_resolve_onebot_ws_settings_normalizes_wildcard_host() -> None:
    cfg = Config()
    fake_driver = SimpleNamespace(config=SimpleNamespace(host="0.0.0.0", port=8080, access_token="abc123"))
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("nonebot.get_driver", return_value=fake_driver),
    ):
        url, _, _ = resolve_onebot_ws_settings(cfg)
    assert url == "ws://127.0.0.1:8080/onebot/v11/ws"


def test_resolve_onebot_ws_settings_env_overrides_driver() -> None:
    cfg = Config()
    fake_driver = SimpleNamespace(config=SimpleNamespace(host="127.0.0.1", port=8080, access_token="driver-token"))
    with (
        patch.dict(
            "os.environ",
            {"HOST": "192.0.2.1", "PORT": "9090", "ACCESS_TOKEN": "env-token"},
            clear=True,
        ),
        patch("nonebot.get_driver", return_value=fake_driver),
    ):
        url, name, token = resolve_onebot_ws_settings(cfg)
    assert url == "ws://192.0.2.1:9090/onebot/v11/ws"
    assert name == "pallas"
    assert token == "env-token"


def test_resolve_onebot_ws_settings_no_host_port_keeps_name_and_hints() -> None:
    cfg = Config()
    fake_driver = SimpleNamespace(config=SimpleNamespace())
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("nonebot.get_driver", return_value=fake_driver),
    ):
        url, name, token = resolve_onebot_ws_settings(cfg)
        hints = onebot_connection_hints(cfg)
    assert url == ""
    assert name == "pallas"
    assert token == ""
    assert hints["onebot_ws_url"] == ""
    assert hints["onebot_ws_name"] == "pallas"
    assert hints["onebot_configured"] is False
