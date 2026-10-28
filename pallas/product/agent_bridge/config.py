"""Strict static MaiBot bridge configuration from ``config/pallas.toml [env]``.

Keys (all ``MAIBOT_BRIDGE_*``): ``ENABLED`` (default false), ``URL``,
``BOT_ID`` (single account) or ``BOT_IDS`` (non-empty JSON list, mutually
exclusive with a non-empty ``BOT_ID``), ``GROUP_IDS`` (JSON list, shared),
``PLATFORM``, optional ``TOKEN``. Explicitly enabling with an unusable value
raises instead of silently guessing an account or group. Disabled config never
validates the other keys.
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
BOT_IDS_KEY = "MAIBOT_BRIDGE_BOT_IDS"
GROUP_IDS_KEY = "MAIBOT_BRIDGE_GROUP_IDS"
PLATFORM_KEY = "MAIBOT_BRIDGE_PLATFORM"
TOKEN_KEY = "MAIBOT_BRIDGE_TOKEN"

BRIDGE_KEYS = (ENABLED_KEY, URL_KEY, BOT_ID_KEY, BOT_IDS_KEY, GROUP_IDS_KEY, PLATFORM_KEY, TOKEN_KEY)

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
    bot_ids: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        effective = frozenset(self.bot_ids)
        if self.bot_id:
            effective = effective | {self.bot_id}
        object.__setattr__(self, "bot_ids", effective)

    def owns_group(self, group_id: int) -> bool:
        return self.enabled and int(group_id) in self.group_ids

    def owns_bot(self, bot_id: object) -> bool:
        try:
            value = int(bot_id)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
        return self.enabled and value in self.bot_ids

    @property
    def multi_account(self) -> bool:
        return len(self.bot_ids) > 1

    @property
    def default_bot_id(self) -> int | None:
        """Single fixed binding only; multi-account never guesses a first account."""
        return self.bot_id or None


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


def parse_bot_ids(raw: Mapping[str, object]) -> frozenset[int]:
    """Resolve the account set from ``BOT_IDS`` (list) or legacy single ``BOT_ID``.

    Non-empty ``BOT_IDS`` and non-empty ``BOT_ID`` are mutually exclusive; neither
    present is an explicit error (never guess the first account).
    """
    single = str(raw.get(BOT_ID_KEY) or "").strip()
    many = str(raw.get(BOT_IDS_KEY) or "").strip()
    if single and many:
        raise BridgeConfigError(f"{BOT_ID_KEY} and {BOT_IDS_KEY} are mutually exclusive")
    if many:
        try:
            data = json.loads(many)
        except ValueError as exc:
            raise BridgeConfigError(f"{BOT_IDS_KEY} must be a JSON list of positive integers") from exc
        if not isinstance(data, list) or not data:
            raise BridgeConfigError(f"{BOT_IDS_KEY} must be a non-empty JSON list of positive integers")
        ids = frozenset(parse_positive_int(item, BOT_IDS_KEY) for item in data)
        if not ids:
            raise BridgeConfigError(f"{BOT_IDS_KEY} must be a non-empty JSON list of positive integers")
        return ids
    if single:
        return frozenset({parse_positive_int(single, BOT_ID_KEY)})
    raise BridgeConfigError(f"enabling the bridge requires {BOT_ID_KEY} or {BOT_IDS_KEY}")


def parse_bridge_config(raw: Mapping[str, object]) -> MaiBotBridgeConfig:
    """Pure parser; ``raw`` maps each ``BRIDGE_KEYS`` entry to a raw value."""
    enabled = parse_enabled(raw.get(ENABLED_KEY))
    if not enabled:
        return MaiBotBridgeConfig(enabled=False)
    url = parse_bridge_url(raw.get(URL_KEY))
    platform = parse_header_value(raw.get(PLATFORM_KEY), PLATFORM_KEY)
    if not platform:
        raise BridgeConfigError(f"{PLATFORM_KEY} is required when the bridge is enabled")
    bot_ids = parse_bot_ids(raw)
    single = next(iter(bot_ids)) if len(bot_ids) == 1 else 0
    return MaiBotBridgeConfig(
        enabled=True,
        url=url,
        bot_id=single,
        bot_ids=bot_ids,
        group_ids=parse_group_ids(raw.get(GROUP_IDS_KEY)),
        platform=platform,
        token=parse_header_value(raw.get(TOKEN_KEY), TOKEN_KEY),
    )


def load_bridge_config() -> MaiBotBridgeConfig:
    raw = {key: repo_env_raw_value(key) for key in BRIDGE_KEYS}
    return parse_bridge_config(raw)
