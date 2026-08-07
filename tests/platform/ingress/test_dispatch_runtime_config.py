from __future__ import annotations

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


def test_message_runtime_defaults_to_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "dispatch_env_raw", lambda _key: None)

    cfg = config.IngressDispatchRuntimeConfig.from_env()

    assert cfg.message_runtime_mode == "legacy"
    assert cfg.message_runtime_canary_groups == ()
    assert cfg.message_runtime_telemetry_enabled is False


def test_message_runtime_reads_shadow_mode_and_valid_canary_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config,
        "dispatch_env_raw",
        lambda key: {
            "PALLAS_MESSAGE_RUNTIME_MODE": "shadow",
            "PALLAS_MESSAGE_RUNTIME_CANARY_GROUPS": "100, nope, 200, -3, 100",
            "PALLAS_MESSAGE_RUNTIME_TELEMETRY_ENABLED": "true",
        }.get(key),
    )

    cfg = config.IngressDispatchRuntimeConfig.from_env()

    assert cfg.message_runtime_mode == "shadow"
    assert cfg.message_runtime_canary_groups == (100, 200)
    assert cfg.message_runtime_telemetry_enabled is True
