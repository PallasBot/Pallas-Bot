"""Focused tests for the static MaiBot bridge config parser."""

import pytest

from pallas.product.agent_bridge.config import (
    BOT_ID_KEY,
    ENABLED_KEY,
    GROUP_IDS_KEY,
    PLATFORM_KEY,
    URL_KEY,
    BridgeConfigError,
    parse_bridge_config,
    parse_enabled,
    parse_group_ids,
)

_ENABLED_BASE = {
    ENABLED_KEY: "true",
    URL_KEY: "ws://127.0.0.1:18000/ws",
    BOT_ID_KEY: "10001",
    GROUP_IDS_KEY: "[700001, 700002]",
    PLATFORM_KEY: "pallas-qq",
}


def test_default_disabled_when_absent():
    config = parse_bridge_config({})
    assert config.enabled is False
    assert config.group_ids == frozenset()


def test_disabled_never_validates_other_keys():
    config = parse_bridge_config({ENABLED_KEY: "false", BOT_ID_KEY: "not-a-number", GROUP_IDS_KEY: "not-json"})
    assert config.enabled is False


def test_enabled_parses_valid_config():
    config = parse_bridge_config(_ENABLED_BASE)
    assert config.enabled is True
    assert config.bot_id == 10001
    assert config.group_ids == frozenset({700001, 700002})
    assert config.platform == "pallas-qq"
    assert config.token == ""


@pytest.mark.parametrize("missing", [URL_KEY, BOT_ID_KEY, GROUP_IDS_KEY, PLATFORM_KEY])
def test_enabled_without_required_key_raises(missing):
    raw = {key: value for key, value in _ENABLED_BASE.items() if key != missing}
    with pytest.raises(BridgeConfigError):
        parse_bridge_config(raw)


def test_invalid_enabled_value_raises_instead_of_enabling():
    with pytest.raises(BridgeConfigError):
        parse_bridge_config({ENABLED_KEY: "maybe"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, False), ("", False), ("TRUE", True), ("1", True), ("off", False), ("no", False)],
)
def test_parse_enabled_variants(raw, expected):
    assert parse_enabled(raw) is expected


@pytest.mark.parametrize("raw", ["[]", "not-json", "[0]", "[-1]", '["a"]', "123", "[700001, 0]"])
def test_group_ids_rejects_bad_values(raw):
    with pytest.raises(BridgeConfigError):
        parse_group_ids(raw)


def test_owns_group_only_when_enabled_and_listed():
    config = parse_bridge_config(_ENABLED_BASE)
    assert config.owns_group(700001) is True
    assert config.owns_group(700002) is True
    assert config.owns_group(700003) is False
    disabled = parse_bridge_config({ENABLED_KEY: "false"})
    assert disabled.owns_group(700001) is False


@pytest.mark.parametrize("raw", ["9" * 40, "0", "-1", "1.5", "0x10", "١٢٣"])
def test_bot_id_rejects_oversized_or_non_decimal(raw):
    with pytest.raises(BridgeConfigError):
        parse_bridge_config({**_ENABLED_BASE, BOT_ID_KEY: raw})


@pytest.mark.parametrize("url", ["garbage", "http://x/ws", "ws://", "//host/ws", "ftp://h"])
def test_url_must_be_absolute_ws_or_wss(url):
    with pytest.raises(BridgeConfigError):
        parse_bridge_config({**_ENABLED_BASE, URL_KEY: url})


def test_valid_ws_and_wss_urls_accepted():
    assert parse_bridge_config({**_ENABLED_BASE, URL_KEY: "ws://127.0.0.1:18000/ws"}).url == "ws://127.0.0.1:18000/ws"
    assert parse_bridge_config({**_ENABLED_BASE, URL_KEY: "wss://bot.example/ws"}).url == "wss://bot.example/ws"


@pytest.mark.parametrize("field", [PLATFORM_KEY, "MAIBOT_BRIDGE_TOKEN"])
def test_header_values_reject_crlf(field):
    with pytest.raises(BridgeConfigError):
        parse_bridge_config({**_ENABLED_BASE, field: "value\r\nX-Injected: 1"})
