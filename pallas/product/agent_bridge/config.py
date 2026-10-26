"""Strict static MaiBot bridge configuration from ``config/pallas.toml [env]``.

Keys (all ``MAIBOT_BRIDGE_*``): ``ENABLED`` (default false), ``URL``,
``BOT_ID``, ``GROUP_IDS`` (JSON list), ``PLATFORM``, optional ``TOKEN``.
Explicitly enabling with an unusable value raises instead of silently guessing
an account or group. Disabled config never validates the other keys.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pallas.core.foundation.config.repo_settings import repo_env_raw_value

if TYPE_CHECKING:
    from collections.abc import Mapping

ENABLED_KEY = "MAIBOT_BRIDGE_ENABLED"
URL_KEY = "MAIBOT_BRIDGE_URL"
BOT_ID_KEY = "MAIBOT_BRIDGE_BOT_ID"
GROUP_IDS_KEY = "MAIBOT_BRIDGE_GROUP_IDS"
PLATFORM_KEY = "MAIBOT_BRIDGE_PLATFORM"
TOKEN_KEY = "MAIBOT_BRIDGE_TOKEN"

BRIDGE_KEYS = (ENABLED_KEY, URL_KEY, BOT_ID_KEY, GROUP_IDS_KEY, PLATFORM_KEY, TOKEN_KEY)

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_ID_MAX_DIGITS = 18
_URL_SCHEMES = frozenset({"ws", "wss"})


class BridgeConfigError(RuntimeError):
    """Raised when the bridge is explicitly enabled but its config is unusable."""


@dataclass(frozen=True)
class MaiBotBridgeConfig:
    enabled: bool = False
    url: str = ""
    bot_id: int = 0
    group_ids: frozenset[int] = frozenset()
    platform: str = ""
    token: str = ""

    def owns_group(self, group_id: int) -> bool:
        return self.enabled and int(group_id) in self.group_ids


def parse_enabled(raw: object) -> bool:
    if raw is None:
        return False
    text = str(raw).strip().lower()
    if not text:
        return False
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise BridgeConfigError(f"{ENABLED_KEY} must be a boolean, got {raw!r}")


def parse_positive_int(raw: object, key: str) -> int:
    if isinstance(raw, bool):
        raise BridgeConfigError(f"{key} must be a positive integer")
    if isinstance(raw, int):
        value = raw
    else:
        text = str(raw or "").strip()
        if not text.isascii() or not text.isdigit() or len(text) > _ID_MAX_DIGITS:
            raise BridgeConfigError(f"{key} must be a positive integer")
        value = int(text)
    if value <= 0:
        raise BridgeConfigError(f"{key} must be a positive integer")
    return value


def parse_bridge_url(raw: object) -> str:
    from urllib.parse import urlsplit

    url = str(raw or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in _URL_SCHEMES or not parts.netloc:
        raise BridgeConfigError(f"{URL_KEY} must be an absolute ws:// or wss:// URL")
    return url


def parse_header_value(raw: object, key: str) -> str:
    value = str(raw or "").strip()
    if any(ch in value for ch in "\r\n"):
        raise BridgeConfigError(f"{key} must not contain CR/LF")
    return value


def parse_group_ids(raw: object) -> frozenset[int]:
    if raw is None:
        raise BridgeConfigError(f"{GROUP_IDS_KEY} is required when the bridge is enabled")
    try:
        data = json.loads(str(raw))
    except ValueError as exc:
        raise BridgeConfigError(f"{GROUP_IDS_KEY} must be a JSON list of positive integers") from exc
    if not isinstance(data, list) or not data:
        raise BridgeConfigError(f"{GROUP_IDS_KEY} must be a non-empty JSON list of positive integers")
    return frozenset(parse_positive_int(item, GROUP_IDS_KEY) for item in data)


def parse_bridge_config(raw: Mapping[str, object]) -> MaiBotBridgeConfig:
    """Pure parser; ``raw`` maps each ``BRIDGE_KEYS`` entry to a raw value."""
    enabled = parse_enabled(raw.get(ENABLED_KEY))
    if not enabled:
        return MaiBotBridgeConfig(enabled=False)
    url = parse_bridge_url(raw.get(URL_KEY))
    platform = parse_header_value(raw.get(PLATFORM_KEY), PLATFORM_KEY)
    if not platform:
        raise BridgeConfigError(f"{PLATFORM_KEY} is required when the bridge is enabled")
    return MaiBotBridgeConfig(
        enabled=True,
        url=url,
        bot_id=parse_positive_int(raw.get(BOT_ID_KEY), BOT_ID_KEY),
        group_ids=parse_group_ids(raw.get(GROUP_IDS_KEY)),
        platform=platform,
        token=parse_header_value(raw.get(TOKEN_KEY), TOKEN_KEY),
    )


def load_bridge_config() -> MaiBotBridgeConfig:
    raw = {key: repo_env_raw_value(key) for key in BRIDGE_KEYS}
    return parse_bridge_config(raw)
