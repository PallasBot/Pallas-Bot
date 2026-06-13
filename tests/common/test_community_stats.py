import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.foundation.apscheduler_runtime import ensure_apscheduler_running, register_apscheduler_startup_hook
from src.features.community_stats import config as cfg_mod
from src.features.community_stats.endpoints import (
    FALLBACK_CORPUS_API_BASE,
    FALLBACK_HEARTBEAT,
    PRIMARY_CORPUS_API_BASE,
    PRIMARY_HEARTBEAT,
    corpus_api_base_from_heartbeat,
    corpus_api_base_urls_for_config,
    heartbeat_urls_for_config,
    is_auto_endpoint_mode,
)
from src.features.community_stats.public_stats import _parse_stats_body
from src.features.community_stats.reporter import (
    build_heartbeat_payload,
    send_community_stats_heartbeat,
    should_run_community_stats_reporter,
)
from src.features.community_stats.scheduler import start_community_stats_reporter
from src.features.community_stats.stats_url import monitor_overview_url_from_endpoint, stats_url_from_endpoint
from src.features.community_stats.store import community_stats_state_path, load_or_create_deployment_id


@pytest.fixture(autouse=True)
def clear_config_cache():
    cfg_mod.clear_community_stats_config_cache()
    yield
    cfg_mod.clear_community_stats_config_cache()


def test_auto_endpoint_mode_builtin_default(monkeypatch):
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENDPOINT", raising=False)
    cfg_mod.clear_community_stats_config_cache()
    cfg = cfg_mod.get_community_stats_config()
    assert is_auto_endpoint_mode(cfg) is True
    assert heartbeat_urls_for_config(cfg)[:2] == [PRIMARY_HEARTBEAT, FALLBACK_HEARTBEAT]


def test_auto_endpoint_custom_url_not_builtin(monkeypatch):
    monkeypatch.setenv("PALLAS_COMMUNITY_STATS_ENDPOINT", "https://stats.example/v1/heartbeat")
    cfg_mod.clear_community_stats_config_cache()
    cfg = cfg_mod.get_community_stats_config()
    assert is_auto_endpoint_mode(cfg) is False
    assert heartbeat_urls_for_config(cfg) == ["https://stats.example/v1/heartbeat"]


def test_stats_url_from_heartbeat_endpoint():
    assert stats_url_from_endpoint("https://stats.pallasbot.top/v1/heartbeat") == "https://stats.pallasbot.top/v1/stats"
    assert stats_url_from_endpoint("") == "https://stats.pallasbot.top/v1/stats"
    assert (
        monitor_overview_url_from_endpoint("https://stats.pallasbot.top/v1/heartbeat")
        == "https://stats.pallasbot.top/v1/monitor/overview"
    )


def test_corpus_api_base_from_heartbeat():
    assert corpus_api_base_from_heartbeat(PRIMARY_HEARTBEAT) == PRIMARY_CORPUS_API_BASE
    assert corpus_api_base_from_heartbeat(FALLBACK_HEARTBEAT) == FALLBACK_CORPUS_API_BASE


def test_corpus_api_base_urls_follow_heartbeat_order(monkeypatch):
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENDPOINT", raising=False)
    cfg_mod.clear_community_stats_config_cache()
    cfg = cfg_mod.get_community_stats_config()
    assert corpus_api_base_urls_for_config(cfg)[:2] == [PRIMARY_CORPUS_API_BASE, FALLBACK_CORPUS_API_BASE]


def test_resolved_community_api_base_urls_auto_mode(monkeypatch):
    monkeypatch.delenv("PALLAS_CORPUS_COMMUNITY_API_BASE", raising=False)
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENDPOINT", raising=False)
    from src.features.corpus.config import clear_corpus_config_cache, resolved_community_api_base_urls

    cfg_mod.clear_community_stats_config_cache()
    clear_corpus_config_cache()
    urls = resolved_community_api_base_urls()
    assert urls[:2] == [PRIMARY_CORPUS_API_BASE, FALLBACK_CORPUS_API_BASE]


def test_parse_stats_body():
    data = _parse_stats_body(
        {
            "deployments_total": 10,
            "deployments_online": 3,
            "bots_online_sum": 7,
            "online_ttl_sec": 900,
            "as_of": "2026-05-22T12:00:00Z",
        },
        "https://stats.example/v1/stats",
    )
    assert data["deployments_total"] == 10
    assert data["online_ttl_sec"] == 900


@pytest.mark.asyncio
async def test_fetch_community_public_stats_parallel_fallback(monkeypatch):
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENDPOINT", raising=False)
    cfg_mod.clear_community_stats_config_cache()

    stats_body = {
        "deployments_total": 1,
        "deployments_online": 1,
        "bots_online_sum": 2,
    }

    async def fake_get(self, url, **kwargs):
        if url.endswith("/monitor/overview"):
            raise httpx.ReadTimeout("overview slow", request=MagicMock())
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = stats_body
        mock.raise_for_status = MagicMock()
        return mock

    with patch.object(httpx.AsyncClient, "get", fake_get):
        from src.features.community_stats.public_stats import fetch_community_public_stats

        data = await fetch_community_public_stats()
    assert data["deployments_online"] == 1
    assert data["stats_url"].endswith("/v1/stats")


def test_parse_monitor_overview_body():
    data = _parse_stats_body(
        {
            "online_ttl_sec": 900,
            "as_of": "2026-05-25T12:00:00Z",
            "corpus_enabled": True,
            "deployments": {
                "deployments_total": 10,
                "deployments_online": 3,
                "bots_online_sum": 7,
                "catalog_bots_online_sum": 9,
                "deployments_online_sharded": 1,
                "shard_workers_online_sum": 2,
                "active_recent_24h": 4,
                "online_versions": [{"version": "3.1.0", "count": 2}],
            },
            "corpus": {
                "contexts_total": 1,
                "answers_total": 2,
                "answer_hits_sum": 5,
                "enrollments_total": 3,
                "enrollments_online": 2,
                "enrollments_recent_24h": 1,
                "read_enabled_total": 3,
                "contribute_enabled_total": 2,
            },
        },
        "https://stats.example/v1/monitor/overview",
    )
    assert data["catalog_bots_online_sum"] == 9
    assert data["corpus"]["enrollments_online"] == 2
    assert data["online_versions"][0]["version"] == "3.1.0"


def test_config_enabled_default_true(monkeypatch):
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENABLED", raising=False)
    with patch("src.features.community_stats.config.repo_env_raw_value", return_value=None):
        cfg_mod.clear_community_stats_config_cache()
        assert cfg_mod.get_community_stats_config().enabled is True


def test_config_enabled_from_toml_without_section(tmp_path, monkeypatch):
    cfg = tmp_path / "pallas.toml"
    cfg.write_text('[bootstrap]\nhost = "127.0.0.1"\nport = 8080\n', encoding="utf-8")
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENABLED", raising=False)
    from src.foundation.config import repo_settings as rs

    monkeypatch.setattr(rs, "repo_config_path", lambda: cfg)
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(rs, "repo_env_path", lambda: tmp_path / "missing.env")
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    cfg_mod.clear_community_stats_config_cache()
    assert cfg_mod.get_community_stats_config().enabled is True


def test_config_disabled_from_toml(tmp_path, monkeypatch):
    cfg = tmp_path / "pallas.toml"
    cfg.write_text("[community_stats]\nenabled = false\n", encoding="utf-8")
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENABLED", raising=False)
    from src.foundation.config import repo_settings as rs

    monkeypatch.setattr(rs, "repo_config_path", lambda: cfg)
    monkeypatch.setattr(rs, "repo_webui_settings_path", lambda: tmp_path / "missing.json")
    monkeypatch.setattr(rs, "repo_env_path", lambda: tmp_path / "missing.env")
    monkeypatch.setattr(rs, "_REPO_ROOT", tmp_path)
    cfg_mod.clear_community_stats_config_cache()
    assert cfg_mod.get_community_stats_config().enabled is False


def test_config_can_disable(monkeypatch):
    monkeypatch.setenv("PALLAS_COMMUNITY_STATS_ENABLED", "false")
    cfg_mod.clear_community_stats_config_cache()
    assert cfg_mod.get_community_stats_config().enabled is False


def test_deployment_id_persisted(tmp_path, monkeypatch):
    path = tmp_path / "pallas_config" / "community_stats.json"
    monkeypatch.setattr(
        "src.features.community_stats.store.community_stats_state_path",
        lambda: path,
    )
    a = load_or_create_deployment_id()
    b = load_or_create_deployment_id()
    assert a == b
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["deployment_id"] == a


def test_should_not_run_on_worker(monkeypatch):
    monkeypatch.setenv("PALLAS_COMMUNITY_STATS_ENABLED", "true")
    cfg_mod.clear_community_stats_config_cache()
    with patch("src.features.community_stats.reporter.is_sharded_worker", return_value=True):
        assert should_run_community_stats_reporter() is False


def test_ensure_apscheduler_running_starts_when_stopped():
    mock_sched = MagicMock()
    mock_sched.running = False
    with patch("nonebot_plugin_apscheduler.scheduler", mock_sched):
        ensure_apscheduler_running()
    mock_sched.start.assert_called_once()


def test_register_apscheduler_startup_hook_idempotent():
    import sys

    import src.foundation.apscheduler_runtime as mod

    mod._HOOK_REGISTERED = False
    mock_driver = MagicMock()
    stub = MagicMock()
    with (
        patch.object(mod, "get_driver", return_value=mock_driver),
        patch.dict(sys.modules, {"nonebot_plugin_apscheduler": stub}),
    ):
        register_apscheduler_startup_hook()
        register_apscheduler_startup_hook()
    assert mod._HOOK_REGISTERED is True
    assert mock_driver.on_startup.call_count == 1


@pytest.mark.asyncio
async def test_start_community_stats_reporter_registers_job(monkeypatch):
    mock_sched = MagicMock()
    mock_sched.running = True
    mock_sched.get_job.return_value = None
    cfg_mod.clear_community_stats_config_cache()
    with (
        patch("src.features.community_stats.scheduler.scheduler", mock_sched),
        patch(
            "src.features.community_stats.scheduler.should_run_community_stats_reporter",
            return_value=True,
        ),
    ):
        await start_community_stats_reporter()
    mock_sched.add_job.assert_called_once()


@pytest.mark.asyncio
async def test_send_heartbeat_success(monkeypatch):
    monkeypatch.setenv("PALLAS_COMMUNITY_STATS_ENDPOINT", "https://stats.example/v1/heartbeat")
    monkeypatch.setenv("PALLAS_COMMUNITY_STATS_TOKEN", "secret")
    cfg_mod.clear_community_stats_config_cache()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"ok":true}'

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "src.features.community_stats.store.community_stats_state_path",
            return_value=community_stats_state_path(),
        ),
        patch(
            "src.features.community_stats.reporter.load_or_create_deployment_id",
            return_value="550e8400-e29b-41d4-a716-446655440000",
        ),
        patch(
            "src.platform.shard.presence.count_connected_bots_for_reporting",
            return_value=1,
        ),
        patch("src.features.community_stats.reporter.get_catalog_bot_ids", return_value=frozenset({1, 2})),
        patch("src.features.community_stats.reporter.httpx.AsyncClient", return_value=mock_client),
    ):
        assert await send_community_stats_heartbeat() is True
        mock_client.post.assert_awaited_once()
        _args, kwargs = mock_client.post.await_args
        assert kwargs["headers"]["Authorization"] == "Bearer secret"
        assert kwargs["json"]["online_bots"] == 1
        assert kwargs["json"]["catalog_bots"] == 2


def test_build_payload_sharded():
    shard = MagicMock()
    shard.id = 0
    with (
        patch("src.features.community_stats.reporter.is_sharding_active", return_value=True),
        patch(
            "src.platform.shard.presence.count_connected_bots_for_reporting",
            return_value=2,
        ),
        patch("src.features.community_stats.reporter.get_catalog_bot_ids", return_value=frozenset({111, 222, 333})),
        patch("src.features.community_stats.reporter.get_shard_registry") as mock_reg,
        patch("src.features.community_stats.reporter.is_test_shard_record", return_value=False),
        patch(
            "src.features.community_stats.reporter.load_or_create_deployment_id",
            return_value="550e8400-e29b-41d4-a716-446655440000",
        ),
        patch("src.features.community_stats.reporter.get_community_stats_config") as mock_cfg,
    ):
        mock_cfg.return_value.roster_public = False
        mock_reg.return_value.shards = [shard, shard]
        payload = build_heartbeat_payload()
        assert payload["sharded"] is True
        assert payload["online_bots"] == 2
        assert payload["catalog_bots"] == 3
        assert payload["shard_workers"] == 2
        assert payload["roster_public"] is False


def test_build_payload_non_sharded_catalog_from_block_bots(monkeypatch):
    class FakeCfg:
        bots = {111, 222, 333}

    import src.plugins.block as block_mod

    monkeypatch.setattr(block_mod, "plugin_config", FakeCfg())
    with (
        patch("src.features.community_stats.reporter.is_sharding_active", return_value=False),
        patch(
            "src.platform.shard.presence.count_connected_bots_for_reporting",
            return_value=2,
        ),
        patch(
            "src.features.community_stats.reporter.load_or_create_deployment_id",
            return_value="550e8400-e29b-41d4-a716-446655440000",
        ),
        patch("src.features.community_stats.reporter.get_community_stats_config") as mock_cfg,
    ):
        mock_cfg.return_value.roster_public = False
        payload = build_heartbeat_payload()
    assert payload["catalog_bots"] == 3
    assert payload["online_bots"] == 2
    assert payload["roster_public"] is False


def test_build_payload_roster_public(monkeypatch):
    monkeypatch.setenv("PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC", "true")
    cfg_mod.clear_community_stats_config_cache()
    roster = [{"qq": 10001, "nickname": "测试牛", "online": True, "message_weight": 42}]
    with (
        patch("src.features.community_stats.reporter.is_sharding_active", return_value=False),
        patch(
            "src.platform.shard.presence.count_connected_bots_for_reporting",
            return_value=1,
        ),
        patch("src.features.community_stats.reporter.get_catalog_bot_ids", return_value=frozenset({10001})),
        patch(
            "src.features.community_stats.reporter.load_or_create_deployment_id",
            return_value="550e8400-e29b-41d4-a716-446655440000",
        ),
        patch("src.features.community_stats.roster.build_public_roster_entries", return_value=roster),
    ):
        payload = build_heartbeat_payload()
    assert payload["roster_public"] is True
    assert payload["roster"] == roster


def test_config_roster_public_default_false(monkeypatch):
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC", raising=False)
    cfg_mod.clear_community_stats_config_cache()
    assert cfg_mod.get_community_stats_config().roster_public is False


def test_config_roster_public_enabled(monkeypatch):
    monkeypatch.setenv("PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC", "true")
    cfg_mod.clear_community_stats_config_cache()
    assert cfg_mod.get_community_stats_config().roster_public is True


@pytest.mark.asyncio
async def test_send_heartbeat_fallback_after_primary_fails(monkeypatch, tmp_path):
    monkeypatch.delenv("PALLAS_COMMUNITY_STATS_ENDPOINT", raising=False)
    cfg_mod.clear_community_stats_config_cache()
    state_path = tmp_path / "pallas_config" / "community_stats.json"
    monkeypatch.setattr(
        "src.features.community_stats.store.community_stats_state_path",
        lambda: state_path,
    )

    calls: list[str] = []

    async def fake_post(self, url, **kwargs):
        calls.append(url)
        mock = MagicMock()
        if url == PRIMARY_HEARTBEAT:
            raise httpx.ConnectError("ssl eof", request=MagicMock())
        mock.status_code = 200
        mock.text = '{"ok":true}'
        return mock

    with (
        patch(
            "src.features.community_stats.reporter.load_or_create_deployment_id",
            return_value="550e8400-e29b-41d4-a716-446655440000",
        ),
        patch(
            "src.platform.shard.presence.count_connected_bots_for_reporting",
            return_value=1,
        ),
        patch("src.features.community_stats.reporter.get_catalog_bot_ids", return_value=frozenset({1})),
        patch.object(httpx.AsyncClient, "post", fake_post),
    ):
        assert await send_community_stats_heartbeat() is True
    assert calls[0] == PRIMARY_HEARTBEAT
    assert calls[1] == FALLBACK_HEARTBEAT
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert raw["heartbeat_endpoint"] == FALLBACK_HEARTBEAT


@pytest.mark.asyncio
async def test_worker_startup_skips_bootstrap_and_enroll(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.plugins.community_stats as plugin_mod

    bootstrap = AsyncMock()
    enroll = AsyncMock()
    reporter = AsyncMock()

    monkeypatch.setattr(plugin_mod, "is_sharded_worker", lambda: True)
    monkeypatch.setattr(plugin_mod, "ensure_control_plane_bootstrap", bootstrap)
    monkeypatch.setattr(plugin_mod, "ensure_corpus_community_enrolled", enroll)
    monkeypatch.setattr(plugin_mod, "start_community_stats_reporter", reporter)

    await plugin_mod.community_stats_startup()

    bootstrap.assert_not_awaited()
    enroll.assert_not_awaited()
    reporter.assert_not_awaited()
