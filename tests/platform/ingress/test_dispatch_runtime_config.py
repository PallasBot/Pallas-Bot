from __future__ import annotations

from typing import Any

import pytest

from pallas.core.foundation.db import pool_budget
from pallas.core.platform.ingress import dispatch_runtime_config as config


@pytest.fixture(autouse=True)
def clear_config_cache() -> None:
    config.clear_ingress_dispatch_runtime_config_cache()
    pool_budget.clear_pool_budget_runtime_cache()
    yield
    config.clear_ingress_dispatch_runtime_config_cache()
    pool_budget.clear_pool_budget_runtime_cache()


def test_conversation_scheduler_defaults_follow_pool_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config,
        "dispatch_env_raw",
        lambda key: {"PG_POOL_SIZE": "12", "PG_MAX_OVERFLOW": "8"}.get(key),
    )
    monkeypatch.setattr(
        pool_budget,
        "repo_env_raw_value",
        lambda key: {"PG_POOL_SIZE": "12", "PG_MAX_OVERFLOW": "8"}.get(key),
    )
    cfg = config.IngressDispatchRuntimeConfig.from_env()

    assert cfg.conversation_scheduler_enabled is True
    assert cfg.conversation_scheduler_concurrency == 8
    assert cfg.conversation_scheduler_max_pending == 512
    assert cfg.conversation_scheduler_per_key_pending == 32


def test_conversation_scheduler_reads_explicit_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config,
        "dispatch_env_raw",
        lambda key: {
            "PALLAS_CONVERSATION_SCHEDULER_ENABLED": "false",
            "PALLAS_CONVERSATION_SCHEDULER_CONCURRENCY": "9",
            "PALLAS_CONVERSATION_SCHEDULER_MAX_PENDING": "1024",
            "PALLAS_CONVERSATION_SCHEDULER_PER_KEY_PENDING": "12",
        }.get(key),
    )
    cfg = config.IngressDispatchRuntimeConfig.from_env()

    assert cfg.conversation_scheduler_enabled is False
    assert cfg.conversation_scheduler_concurrency == 9
    assert cfg.conversation_scheduler_max_pending == 1024
    assert cfg.conversation_scheduler_per_key_pending == 12


def test_chat_lane_adaptive_max_reads_explicit_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config,
        "dispatch_env_raw",
        lambda key: {"PALLAS_LANE_CHAT_ADAPTIVE_MAX": "14"}.get(key),
    )

    assert config.IngressDispatchRuntimeConfig.from_env().lane_chat_adaptive_max == 14


def test_dispatch_env_float_applies_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "dispatch_env_raw", lambda key: {"PALLAS_X": "0.25"}.get(key))

    assert config.dispatch_env_float("PALLAS_X", default=1.0, minimum=0.5) == 0.5


@pytest.mark.parametrize("raw", ["inf", "-inf", "nan"])
def test_dispatch_env_float_rejects_non_finite_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setattr(config, "dispatch_env_raw", lambda _key: raw)

    assert config.dispatch_env_float("PALLAS_X", default=1.0, minimum=0.5) == 1.0


def test_lane_defaults_follow_fleet_scale_and_pool_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    env_values = {"PG_POOL_SIZE": "12", "PG_MAX_OVERFLOW": "8"}
    monkeypatch.setattr(config, "dispatch_env_raw", env_values.get)
    monkeypatch.setattr(pool_budget, "repo_env_raw_value", env_values.get)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fleet_dispatch_scale.connected_bot_count",
        lambda: 7,
    )
    pool_budget.clear_pool_budget_runtime_cache()

    cfg = config.IngressDispatchRuntimeConfig.from_env()

    assert cfg.lane_command == 16
    assert cfg.lane_chat == 6
    assert cfg.lane_storage == 8
    assert cfg.lane_remote == 7


def test_lane_limits_keep_legacy_alias_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config,
        "dispatch_env_raw",
        lambda key: {
            "PALLAS_LANE_COMMAND_EXACT": "11",
            "PALLAS_LANE_PASSIVE_AI": "9",
        }.get(key),
    )

    cfg = config.IngressDispatchRuntimeConfig.from_env()

    assert cfg.lane_command == 11
    assert cfg.lane_remote == 9


def test_send_queue_max_depth_floor_is_32(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "dispatch_env_raw", lambda key: {"PALLAS_SEND_QUEUE_MAX_DEPTH": "16"}.get(key))

    assert config.IngressDispatchRuntimeConfig.from_env().send_queue_max_depth == 32


def test_runtime_config_snapshot_rebuilds_when_disk_revision_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    state: dict[str, Any] = {"rev": ((1, 1),), "env": {}}
    monkeypatch.setattr(config, "repo_settings_disk_revision", lambda: state["rev"])
    monkeypatch.setattr(config, "dispatch_env_raw", lambda key: state["env"].get(key))

    first = config.get_ingress_dispatch_runtime_config()
    assert config.get_ingress_dispatch_runtime_config() is first

    state["env"]["PALLAS_SEND_QUEUE_MAX_DEPTH"] = "1024"
    assert config.get_ingress_dispatch_runtime_config() is first

    state["rev"] = ((2, 2),)
    rebuilt = config.get_ingress_dispatch_runtime_config()
    assert rebuilt is not first
    assert rebuilt.send_queue_max_depth == 1024
