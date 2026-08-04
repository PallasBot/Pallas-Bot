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
    assert cfg.conversation_scheduler_concurrency == 6
    assert cfg.conversation_scheduler_max_pending == 512


def test_conversation_scheduler_reads_explicit_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config,
        "dispatch_env_raw",
        lambda key: {
            "PALLAS_CONVERSATION_SCHEDULER_ENABLED": "false",
            "PALLAS_CONVERSATION_SCHEDULER_CONCURRENCY": "9",
            "PALLAS_CONVERSATION_SCHEDULER_MAX_PENDING": "1024",
        }.get(key),
    )
    cfg = config.IngressDispatchRuntimeConfig.from_env()

    assert cfg.conversation_scheduler_enabled is False
    assert cfg.conversation_scheduler_concurrency == 9
    assert cfg.conversation_scheduler_max_pending == 1024
