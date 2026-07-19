from nonebot.plugin import PluginMetadata

from pallas.core.plugin_reload import (
    DEFAULT_RELOAD_POLICY,
    normalize_reload_policy,
    reload_policy_from_metadata,
)


def test_normalize_reload_policy_defaults():
    assert normalize_reload_policy(None) == DEFAULT_RELOAD_POLICY
    assert normalize_reload_policy("unknown") == DEFAULT_RELOAD_POLICY
    assert normalize_reload_policy("metadata") == "metadata"
    assert normalize_reload_policy("FULL") == "full"


def test_reload_policy_from_metadata():
    meta = PluginMetadata(
        name="t",
        description="t。",
        usage="",
        extra={"reload_policy": "metadata"},
    )
    assert reload_policy_from_metadata(meta) == "metadata"
    assert reload_policy_from_metadata(None) == DEFAULT_RELOAD_POLICY
