"""shard_metric_hydrate：worker 不得回灌共享落盘。"""

from __future__ import annotations

import json

from pallas.product.llm.shard_metric_hydrate import (
    allow_shared_stats_file_hydrate,
    is_sharded_worker,
    load_worker_day_metric,
)


def test_allow_shared_stats_file_hydrate_false_on_worker(monkeypatch) -> None:
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.context.is_worker", lambda: True)
    assert is_sharded_worker() is True
    assert allow_shared_stats_file_hydrate() is False


def test_allow_shared_stats_file_hydrate_true_on_hub(monkeypatch) -> None:
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.context.is_worker", lambda: False)
    assert is_sharded_worker() is False
    assert allow_shared_stats_file_hydrate() is True


def test_worker_token_hydrate_skips_shared_file(tmp_path, monkeypatch) -> None:
    from pallas.product.llm import token_metrics as tm

    tm.clear_llm_token_metrics_for_tests()
    path = tmp_path / "llm_token_stats.json"
    path.write_text(
        json.dumps({
            "v": 1,
            "day_key": tm.today_key(),
            "prompt_tokens": 999,
            "completion_tokens": 1,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost_total": 0,
            "by_task": {},
            "by_provider": {},
            "by_model": {},
            "by_hour": {},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(tm, "stats_file_path", lambda: path)
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.context.is_worker", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.context.shard_id", lambda: 1)
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.read_worker_stats_file",
        lambda shard_id: {},
    )

    snap = tm.llm_token_metrics_snapshot(include_persisted=True)
    assert snap["prompt_tokens"] == 0
    assert snap["completion_tokens"] == 0
    tm.clear_llm_token_metrics_for_tests()


def test_load_worker_day_metric_requires_matching_day(monkeypatch) -> None:
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.context.is_worker", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.context.shard_id", lambda: 3)
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.read_worker_stats_file",
        lambda shard_id: {"llm_token": {"day_key": "2020-01-01", "prompt_tokens": 5}},
    )
    assert load_worker_day_metric(metric_key="llm_token", day_key="2026-07-27") is None
