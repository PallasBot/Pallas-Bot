"""Bot 侧 LLM token 计量。"""

from __future__ import annotations

import json

import pytest

from pallas.product.llm.token_metrics import (
    clear_llm_token_metrics_for_tests,
    llm_token_metrics_snapshot,
    record_llm_token_usage,
)
from pallas.product.llm.token_usage import usage_from_local_chat_response, usage_from_remote_chat_response


def test_record_llm_token_usage_with_cache() -> None:
    clear_llm_token_metrics_for_tests()
    record_llm_token_usage(
        task="llm_chat",
        provider="openai",
        model="gpt-4.1-mini",
        prompt_tokens=80,
        completion_tokens=20,
        cache_read_tokens=40,
        cache_write_tokens=10,
    )
    snap = llm_token_metrics_snapshot(include_persisted=False)
    assert snap["prompt_tokens"] == 80
    assert snap["completion_tokens"] == 20
    assert snap["cache_read_tokens"] == 40
    assert snap["cache_write_tokens"] == 10
    assert snap["total_tokens"] == 100
    assert snap["by_model"]["gpt-4.1-mini"]["cache_read_tokens"] == 40
    assert snap["by_provider"]["openai"]["total_tokens"] == 100


def test_cluster_llm_token_metrics_merges_worker_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import token_metrics as tm

    clear_llm_token_metrics_for_tests()
    record_llm_token_usage(
        task="llm_chat",
        provider="hub",
        model="hub-model",
        prompt_tokens=10,
        completion_tokens=5,
    )
    day = tm.today_key()

    class _Ctx:
        @staticmethod
        def sharding_active() -> bool:
            return True

        @staticmethod
        def is_hub() -> bool:
            return True

    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", _Ctx.sharding_active)
    monkeypatch.setattr("pallas.core.platform.shard.context.is_hub", _Ctx.is_hub)
    monkeypatch.setattr(tm, "load_stats_file", dict)
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.iter_worker_shard_ids",
        lambda max_stale_sec=300.0: [1],
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.read_worker_stats_file",
        lambda shard_id: {
            "llm_token": {
                "source": "bot",
                "day_key": day,
                "prompt_tokens": 30,
                "completion_tokens": 20,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 50,
                "by_provider": {
                    "ds": {
                        "prompt_tokens": 30,
                        "completion_tokens": 20,
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                        "total_tokens": 50,
                    }
                },
                "by_model": {},
                "by_task": {},
            }
        },
    )

    merged = tm.cluster_llm_token_metrics_snapshot()
    assert merged["source"] == "bot_cluster"
    assert merged["prompt_tokens"] == 40
    assert merged["completion_tokens"] == 25
    assert merged["total_tokens"] == 65
    assert merged["by_provider"]["hub"]["total_tokens"] == 15
    assert merged["by_provider"]["ds"]["total_tokens"] == 50


def test_flush_does_not_double_count(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import token_metrics as tm

    clear_llm_token_metrics_for_tests()
    path = tmp_path / "llm_token_stats.json"
    monkeypatch.setattr(tm, "stats_file_path", lambda: path)

    record_llm_token_usage(
        task="llm_chat",
        provider="openai",
        model="m",
        prompt_tokens=100,
        completion_tokens=20,
    )
    tm.flush_stats_sync()
    tm.flush_stats_sync()
    tm.flush_stats_sync()
    snap = llm_token_metrics_snapshot(include_persisted=True)
    assert snap["total_tokens"] == 120
    assert snap["prompt_tokens"] == 100
    assert int(json.loads(path.read_text(encoding="utf-8"))["total_tokens"]) == 120


def test_hydrate_from_disk_after_restart(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import token_metrics as tm

    clear_llm_token_metrics_for_tests()
    path = tmp_path / "llm_token_stats.json"
    monkeypatch.setattr(tm, "stats_file_path", lambda: path)

    record_llm_token_usage(task="llm_chat", provider="x", model="m", prompt_tokens=40, completion_tokens=10)
    tm.flush_stats_sync()

    tm._day_key = ""
    tm._hydrated = False
    tm._prompt_tokens = 0
    tm._completion_tokens = 0
    tm._cache_read_tokens = 0
    tm._cache_write_tokens = 0
    tm._cost_total = 0.0
    tm._cost_currency = ""
    tm._by_task.clear()
    tm._by_provider.clear()
    tm._by_model.clear()
    tm._by_hour.clear()

    snap = llm_token_metrics_snapshot(include_persisted=True)
    assert snap["total_tokens"] == 50
    record_llm_token_usage(task="llm_chat", provider="x", model="m", prompt_tokens=5, completion_tokens=0)
    snap2 = llm_token_metrics_snapshot(include_persisted=True)
    assert snap2["total_tokens"] == 55
    tm.flush_stats_sync()
    assert int(json.loads(path.read_text(encoding="utf-8"))["total_tokens"]) == 55


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"prompt_eval_count": 12, "eval_count": 3}, (12, 3, 0, 0)),
        (
            {"usage": {"prompt_tokens": 100, "completion_tokens": 20}},
            (100, 20, 0, 0),
        ),
        (
            {
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 10,
                    "prompt_tokens_details": {"cached_tokens": 40},
                }
            },
            (80, 10, 40, 0),
        ),
        (
            {
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 30,
                    "cache_creation_input_tokens": 8,
                }
            },
            (70, 5, 30, 8),
        ),
        (
            {
                "usage": {
                    "prompt_tokens": 18234,
                    "completion_tokens": 412,
                    "prompt_cache_hit_tokens": 16000,
                    "prompt_cache_miss_tokens": 2234,
                }
            },
            (2234, 412, 16000, 0),
        ),
        # OpenAI / DeepSeek Responses：input_tokens_details.cached_tokens
        (
            {
                "usage": {
                    "input_tokens": 1296,
                    "input_tokens_details": {"cached_tokens": 1280},
                    "output_tokens": 4,
                    "total_tokens": 1300,
                }
            },
            (16, 4, 1280, 0),
        ),
        # miss 字段优先于 prompt_raw - cache_read
        (
            {
                "usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 1,
                    "prompt_cache_hit_tokens": 100,
                    "prompt_cache_miss_tokens": 95,
                }
            },
            (95, 1, 100, 0),
        ),
    ],
)
def test_usage_parsers(data: dict, expected: tuple[int, int, int, int]) -> None:
    if "usage" in data:
        assert usage_from_remote_chat_response(data) == expected
    else:
        assert usage_from_local_chat_response(data) == expected
