"""从 PluginMetadata.extra 解析 reload_policy（代码级重载尚未实现）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from nonebot.plugin import PluginMetadata

ReloadPolicy = Literal["config_only", "metadata", "full"]

DEFAULT_RELOAD_POLICY: ReloadPolicy = "config_only"
VALID_RELOAD_POLICIES: frozenset[str] = frozenset({"config_only", "metadata", "full"})


def normalize_reload_policy(raw: str | None) -> ReloadPolicy:
    value = (raw or DEFAULT_RELOAD_POLICY).strip().lower()
    if value not in VALID_RELOAD_POLICIES:
        return DEFAULT_RELOAD_POLICY
    return value  # type: ignore[return-value]


def reload_policy_from_metadata(meta: PluginMetadata | None) -> ReloadPolicy:
    if meta is None or not meta.extra:
        return DEFAULT_RELOAD_POLICY
    raw = meta.extra.get("reload_policy")
    if raw is None:
        return DEFAULT_RELOAD_POLICY
    if not isinstance(raw, str):
        return DEFAULT_RELOAD_POLICY
    return normalize_reload_policy(raw)
