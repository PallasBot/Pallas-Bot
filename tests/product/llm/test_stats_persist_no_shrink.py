"""日汇总写回勿用偏少快照覆盖；RAG 跨日/分片重启可回灌。"""

from __future__ import annotations

import json

from pallas.product.llm.llm_daily_stats_store import merge_side_snapshot
from pallas.product.llm.rag_metrics import (
    clear_llm_rag_metrics_for_tests,
    llm_rag_metrics_snapshot,
)


def test_merge_side_snapshot_does_not_shrink_rag() -> None:
    existing = {
        "rag": {"hit_count": 100, "miss_count": 20, "by_document": {"a": 5}},
        "tokens": {"total_tokens": 1000, "prompt_tokens": 800, "completion_tokens": 200},
    }
    incoming = {
        "rag": {"hit_count": 3, "miss_count": 1, "by_document": {"b": 1}},
        "tokens": {"total_tokens": 50, "prompt_tokens": 40, "completion_tokens": 10},
        "gates": {"proceed": 1, "skip": 0, "defer": 0},
    }
    merged = merge_side_snapshot(existing, incoming)
    assert merged["rag"]["hit_count"] == 100
    assert merged["rag"]["miss_count"] == 20
    assert merged["tokens"]["total_tokens"] == 1000
    assert merged["gates"]["proceed"] == 1


def test_merge_side_snapshot_accepts_higher_rag() -> None:
    existing = {"rag": {"hit_count": 10, "miss_count": 0, "by_document": {}}}
    incoming = {"rag": {"hit_count": 12, "miss_count": 3, "by_document": {"x": 1}}}
    merged = merge_side_snapshot(existing, incoming)
    assert merged["rag"]["hit_count"] == 12
    assert merged["rag"]["miss_count"] == 3


def test_merge_side_snapshot_does_not_shrink_images_buckets() -> None:
    existing = {
        "images": {
            "ok_count": 10,
            "fail_count": 1,
            "image_count": 10,
            "cost_total": 1.0,
            "by_gateway": {"provider": {"ok_count": 10, "fail_count": 1, "image_count": 10, "cost_total": 1.0}},
            "by_provider": {"p1": {"ok_count": 10, "fail_count": 1, "image_count": 10, "cost_total": 1.0}},
            "by_model": {"m1": {"ok_count": 10, "fail_count": 1, "image_count": 10, "cost_total": 1.0}},
        }
    }
    incoming = {
        "images": {
            "ok_count": 2,
            "fail_count": 0,
            "image_count": 2,
            "cost_total": 0.2,
            "by_gateway": {"provider": {"ok_count": 2, "fail_count": 0, "image_count": 2, "cost_total": 0.2}},
            "by_provider": {"p2": {"ok_count": 2, "fail_count": 0, "image_count": 2, "cost_total": 0.2}},
            "by_model": {"m2": {"ok_count": 2, "fail_count": 0, "image_count": 2, "cost_total": 0.2}},
        }
    }
    merged = merge_side_snapshot(existing, incoming)
    img = merged["images"]
    assert img["ok_count"] == 10
    assert img["image_count"] == 10
    assert img["by_provider"]["p1"]["ok_count"] == 10
    assert img["by_provider"]["p2"]["ok_count"] == 2
    assert img["by_model"]["m1"]["ok_count"] == 10
    assert img["by_model"]["m2"]["ok_count"] == 2


def test_merge_side_snapshot_corrects_images_shard_multiple_clone() -> None:
    small = {
        "ok_count": 48,
        "fail_count": 5,
        "image_count": 48,
        "cost_total": 0.9856,
        "cost_currency": "CNY",
        "by_gateway": {
            "manual": {"ok_count": 16, "fail_count": 5, "image_count": 16, "cost_total": 0.0},
            "provider": {"ok_count": 32, "fail_count": 0, "image_count": 32, "cost_total": 0.9856},
        },
        "by_provider": {
            "AK": {"ok_count": 32, "fail_count": 0, "image_count": 32, "cost_total": 0.9856},
            "router.shengsuanyun.com": {"ok_count": 16, "fail_count": 0, "image_count": 16, "cost_total": 0.0},
            "exhausted": {"ok_count": 0, "fail_count": 5, "image_count": 0, "cost_total": 0.0},
        },
        "by_model": {
            "gpt-image-2": {"ok_count": 32, "fail_count": 0, "image_count": 32, "cost_total": 0.9856},
            "openai/gpt-image-2": {"ok_count": 16, "fail_count": 0, "image_count": 16, "cost_total": 0.0},
        },
    }
    factor = 9
    big = {
        "ok_count": small["ok_count"] * factor,
        "fail_count": small["fail_count"] * factor,
        "image_count": small["image_count"] * factor,
        "cost_total": small["cost_total"] * factor,
        "cost_currency": "CNY",
        "by_gateway": {
            k: {
                "ok_count": v["ok_count"] * factor,
                "fail_count": v["fail_count"] * factor,
                "image_count": v["image_count"] * factor,
                "cost_total": v["cost_total"] * factor,
            }
            for k, v in small["by_gateway"].items()
        },
        "by_provider": {
            k: {
                "ok_count": v["ok_count"] * factor,
                "fail_count": v["fail_count"] * factor,
                "image_count": v["image_count"] * factor,
                "cost_total": v["cost_total"] * factor,
            }
            for k, v in small["by_provider"].items()
        },
        "by_model": {
            k: {
                "ok_count": v["ok_count"] * factor,
                "fail_count": v["fail_count"] * factor,
                "image_count": v["image_count"] * factor,
                "cost_total": v["cost_total"] * factor,
            }
            for k, v in small["by_model"].items()
        },
    }
    merged = merge_side_snapshot({"images": big}, {"images": small})
    img = merged["images"]
    assert img["ok_count"] == 48
    assert img["fail_count"] == 5
    assert img["image_count"] == 48
    assert abs(img["cost_total"] - 0.9856) < 1e-9
    assert img["by_provider"]["AK"]["ok_count"] == 32


def test_rag_stale_file_salvaged_and_worker_rehydrates(tmp_path, monkeypatch) -> None:
    clear_llm_rag_metrics_for_tests()
    import pallas.product.llm.rag_metrics as rm

    stats_path = tmp_path / "llm_rag_stats.json"
    monkeypatch.setattr(rm, "stats_file_path", lambda: stats_path)
    monkeypatch.setattr(rm, "today_key", lambda: "2026-07-27")
    written: list[tuple] = []

    def fake_write(day: str, side: str, snapshot: dict) -> None:
        written.append((day, side, snapshot))

    monkeypatch.setattr("pallas.product.llm.llm_daily_stats_store.write_day_side", fake_write)

    stats_path.write_text(
        json.dumps({
            "v": 1,
            "day_key": "2026-07-25",
            "hit_count": 88,
            "miss_count": 2,
            "by_document": {"old": 1},
        }),
        encoding="utf-8",
    )

    with rm._lock:
        rm._day_key = "2026-07-27"
        rm._hydrated = False
        rm._hit_count = 0
        rm._miss_count = 0
        rm._by_document.clear()
        rm._by_source.clear()

    snap = llm_rag_metrics_snapshot(include_persisted=True)
    assert snap["hit_count"] == 0
    assert written
    assert written[0][0] == "2026-07-25"
    assert written[0][2]["rag"]["hit_count"] == 88

    # worker 从自身 stats 回灌当日
    clear_llm_rag_metrics_for_tests()
    monkeypatch.setattr("pallas.core.platform.shard.context.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.context.is_worker", lambda: True)
    monkeypatch.setattr("pallas.core.platform.shard.context.is_hub", lambda: False)
    monkeypatch.setattr("pallas.core.platform.shard.context.shard_id", lambda: 3)
    monkeypatch.setattr(
        "pallas.core.platform.shard.console_stats.read_worker_stats_file",
        lambda shard_id: {
            "llm_rag": {
                "day_key": "2026-07-27",
                "hit_count": 7,
                "miss_count": 4,
                "by_document": {"doc": 2},
                "by_source": {"src": 2},
            }
        },
    )
    with rm._lock:
        rm._day_key = "2026-07-27"
        rm._hydrated = False
        rm._hit_count = 0
        rm._miss_count = 0
        rm._by_document.clear()
        rm._by_source.clear()

    restored = llm_rag_metrics_snapshot(include_persisted=True)
    assert restored["hit_count"] == 7
    assert restored["miss_count"] == 4
    assert restored["by_document"]["doc"] == 2
