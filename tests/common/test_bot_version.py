from unittest.mock import patch

from pallas.core.foundation.bot_version import (
    display_version_without_sha,
    get_pallas_bot_version_for_health,
    get_pallas_bot_version_for_reporting,
)
from pallas.product.community_stats.reporter import build_heartbeat_payload


def test_display_version_without_sha():
    assert display_version_without_sha("v3.1.0+gdeadbeef") == "v3.1.0"
    assert display_version_without_sha("3.0.0 · deadbeef") == "3.0.0"
    assert display_version_without_sha("v1.0.0") == "v1.0.0"


def test_get_pallas_bot_version_for_health_env(monkeypatch):
    monkeypatch.setenv("PALLAS_BOT_VERSION", "v9.9.9")
    assert get_pallas_bot_version_for_health() == "v9.9.9"


def test_get_pallas_bot_version_for_reporting_prefers_exact_tag():
    with patch(
        "pallas.core.foundation.bot_version.get_bot_current_version",
        return_value={"tag": "v3.1.0", "commit": "abc1234"},
    ):
        assert get_pallas_bot_version_for_reporting() == "v3.1.0"


def test_get_pallas_bot_version_for_reporting_falls_back_to_health():
    with (
        patch(
            "pallas.core.foundation.bot_version.get_bot_current_version", return_value={"tag": "", "commit": "abc1234"}
        ),
        patch(
            "pallas.core.foundation.bot_version.get_pallas_bot_version_for_health", return_value="v3.0.0-12-gdeadbeef"
        ),
    ):
        assert get_pallas_bot_version_for_reporting() == "v3.0.0-12-gdeadbeef"


def test_build_heartbeat_payload_uses_runtime_version():
    with (
        patch(
            "pallas.product.community_stats.reporter.get_pallas_bot_version_for_reporting",
            return_value="v3.1.0",
        ),
        patch(
            "pallas.core.platform.shard.presence.count_connected_bots_for_reporting",
            return_value=1,
        ),
        patch("pallas.product.community_stats.reporter.get_catalog_bot_ids", return_value=frozenset({1})),
        patch(
            "pallas.product.community_stats.reporter.load_or_create_deployment_id",
            return_value="550e8400-e29b-41d4-a716-446655440000",
        ),
        patch("pallas.product.community_stats.reporter.is_sharding_active", return_value=False),
    ):
        payload = build_heartbeat_payload()
    assert payload["version"] == "v3.1.0"
