from types import SimpleNamespace
from unittest.mock import patch

from src.plugins.pallas_protocol.config import Config, resolve_onebot_ws_settings


def test_resolve_onebot_ws_settings_fallback_to_driver_config() -> None:
    cfg = Config(
        pallas_protocol_onebot_host="",
        pallas_protocol_onebot_port=None,
        pallas_protocol_access_token="",
    )
    fake_driver = SimpleNamespace(config=SimpleNamespace(host="127.0.0.1", port=8080, access_token="abc123"))
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("nonebot.get_driver", return_value=fake_driver),
    ):
        url, name, token = resolve_onebot_ws_settings(cfg)
    assert url == "ws://127.0.0.1:8080/onebot/v11/ws"
    assert name == "pallas"
    assert token == "abc123"
