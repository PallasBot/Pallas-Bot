from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pallas.product.llm.model_admin import fetch_llm_task_stats


def _patch_bot_snapshots(monkeypatch: pytest.MonkeyPatch, bot_snapshot: dict) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.llm_task_metrics_snapshot",
        lambda: bot_snapshot,
        raising=False,
    )
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.cluster_llm_task_metrics_snapshot",
        lambda: bot_snapshot,
        raising=False,
    )


def _patch_bot_tokens(monkeypatch: pytest.MonkeyPatch, tokens: dict) -> list[tuple[str, str, dict[str, object]]]:
    token_mod = MagicMock()
    token_mod.flush_stats_sync = MagicMock()
    token_mod.llm_token_metrics_snapshot = MagicMock(return_value=tokens)
    monkeypatch.setattr(
        "pallas.product.llm.token_metrics.flush_stats_sync",
        token_mod.flush_stats_sync,
        raising=False,
    )
    monkeypatch.setattr(
        "pallas.product.llm.token_metrics.llm_token_metrics_snapshot",
        token_mod.llm_token_metrics_snapshot,
        raising=False,
    )
    monkeypatch.setattr(
        "pallas.product.llm.provider_request_metrics.flush_provider_request_stats_sync",
        MagicMock(),
        raising=False,
    )
    monkeypatch.setattr(
        "pallas.product.llm.provider_request_metrics.llm_provider_request_metrics_snapshot",
        MagicMock(return_value={}),
        raising=False,
    )
    written: list[tuple[str, str, dict[str, object]]] = []
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.write_llm_daily_stats_side",
        lambda day, side, snapshot: written.append((day, side, snapshot)),
    )
    return written


@pytest.mark.asyncio
async def test_fetch_llm_task_stats_uses_bot_kernel_token_metering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_snapshot = {
        "source": "bot",
        "day_key": "2026-06-18",
        "updated_at": 1.0,
        "by_task": {},
        "totals": {},
    }
    bot_tokens = {
        "source": "bot",
        "day_key": "2026-06-18",
        "prompt_tokens": 123,
        "completion_tokens": 77,
        "total_tokens": 200,
        "by_task": {},
        "by_provider": {},
        "by_model": {},
    }
    _patch_bot_snapshots(monkeypatch, bot_snapshot)
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.today_key",
        lambda: "2026-06-18",
        raising=False,
    )
    written = _patch_bot_tokens(monkeypatch, bot_tokens)
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.load_llm_daily_stats_range",
        lambda *, start_day, end_day: ([], start_day, end_day),
    )

    payload = await fetch_llm_task_stats(start="2026-06-18", end="2026-06-18")

    assert payload["ai_reachable"] is True
    assert payload["persistence"]["ai_reachable"] is True
    assert payload["persistence"]["ai_collecting"] is True
    assert payload["ai"]["source"] == "bot"
    assert payload["ai"]["tokens"]["total_tokens"] == 200
    assert payload["history"]["rows"][0]["ai"]["tokens"]["prompt_tokens"] == 123
    ai_writes = [row for row in written if row[1] == "ai"]
    assert ai_writes
    assert ai_writes[0][0] == "2026-06-18"
    assert ai_writes[0][2]["reachable"] is True


@pytest.mark.asyncio
async def test_fetch_llm_task_stats_normalizes_bot_token_snapshot_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_snapshot = {
        "source": "bot",
        "day_key": "2026-06-18",
        "updated_at": 1.0,
        "by_task": {},
        "totals": {},
    }
    bot_tokens = {
        "source": "bot",
        "day_key": "2026-06-18",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "by_task": {"llm_chat": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        "by_provider": {},
        "by_model": {},
    }
    _patch_bot_snapshots(monkeypatch, bot_snapshot)
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.today_key",
        lambda: "2026-06-18",
        raising=False,
    )
    _patch_bot_tokens(monkeypatch, bot_tokens)
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.load_llm_daily_stats_range",
        lambda *, start_day, end_day: ([], start_day, end_day),
    )

    payload = await fetch_llm_task_stats(start="2026-06-18", end="2026-06-18")

    assert payload["ai_reachable"] is True
    assert payload["ai"]["state_counts"] == {
        "queued": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
    }
    assert payload["ai"]["tokens"]["by_task"]["llm_chat"]["total_tokens"] == 15
    assert payload["ai"]["tokens"]["by_provider"] == {}
    assert payload["ai"]["tokens"]["by_model"] == {}


@pytest.mark.asyncio
async def test_fetch_llm_task_stats_includes_durable_sticker_vision_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_snapshot = {
        "source": "bot",
        "day_key": "2026-06-18",
        "updated_at": 1.0,
        "by_task": {},
        "totals": {},
    }
    _patch_bot_snapshots(monkeypatch, bot_snapshot)
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.today_key",
        lambda: "2026-06-18",
        raising=False,
    )
    _patch_bot_tokens(monkeypatch, {})
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.load_llm_daily_stats_range",
        lambda *, start_day, end_day: ([], start_day, end_day),
    )

    async def fetch_observation() -> dict[str, object]:
        return {"requests": 1, "selected": 1, "failed": 0, "recent": []}

    monkeypatch.setattr(
        "pallas.product.llm.sticker_vision.fetch_sticker_vision_stats",
        fetch_observation,
    )

    payload = await fetch_llm_task_stats(start="2026-06-18", end="2026-06-18")

    assert payload["ai"]["sticker_vision"] == {"requests": 1, "selected": 1, "failed": 0, "recent": []}


@pytest.mark.asyncio
async def test_fetch_llm_task_stats_falls_back_to_latest_history_when_no_live_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_snapshot = {
        "source": "bot",
        "day_key": "2026-06-20",
        "updated_at": 1.0,
        "by_task": {},
        "totals": {},
    }
    historical_ai = {
        "source": "bot",
        "day_key": "2026-06-19",
        "updated_at": 2.0,
        "by_task": {
            "llm_chat": {
                "task_ok": 3,
                "task_fail": 1,
                "route_counts": {
                    "plain_llm_chat": 2,
                    "corpus_select": 1,
                },
            },
            "repeater_polish": {
                "task_ok": 2,
                "task_fail": 0,
                "route_counts": {
                    "pipeline_stitch": 2,
                },
            },
        },
        "totals": {
            "task_ok": 5,
            "task_fail": 1,
        },
        "tokens": {
            "prompt_tokens": 120,
            "completion_tokens": 80,
            "total_tokens": 200,
            "by_provider": {
                "openai": 140,
                "volcengine": 60,
            },
            "by_model": {
                "gpt-4o-mini": 140,
                "doubao-seed": 60,
            },
        },
        "classification": {
            "provider_stats": {
                "openai": {
                    "ok": 3,
                    "fail": 1,
                },
                "volcengine": {
                    "ok": 2,
                    "fail": 0,
                },
            },
            "model_stats": {
                "gpt-4o-mini": {
                    "ok": 3,
                    "fail": 1,
                },
                "doubao-seed": {
                    "ok": 2,
                    "fail": 0,
                },
            },
            "failure_counts": {
                "timeout": 1,
            },
        },
    }

    _patch_bot_snapshots(monkeypatch, bot_snapshot)
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.today_key",
        lambda: "2026-06-20",
        raising=False,
    )
    _patch_bot_tokens(monkeypatch, {})
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.load_llm_daily_stats_range",
        lambda *, start_day, end_day: ([{"date": "2026-06-19", "bot": None, "ai": historical_ai}], start_day, end_day),
    )

    payload = await fetch_llm_task_stats(start="2026-06-19", end="2026-06-20")

    assert payload["ai_reachable"] is True
    assert payload["ai"]["state_counts"] == {
        "queued": 0,
        "running": 0,
        "succeeded": 5,
        "failed": 1,
    }
    assert payload["ai"]["failure_counts"] == {"timeout": 1}
    assert payload["ai"]["provider_stats"] == {
        "openai": {
            "requests": 4,
            "succeeded": 3,
            "failed": 1,
            "total_latency_ms": 0,
            "avg_latency_ms": None,
            "recent_failure_class": None,
        },
        "volcengine": {
            "requests": 2,
            "succeeded": 2,
            "failed": 0,
            "total_latency_ms": 0,
            "avg_latency_ms": None,
            "recent_failure_class": None,
        },
    }
    assert payload["ai"]["model_stats"] == {
        "gpt-4o-mini": {
            "requests": 4,
            "succeeded": 3,
            "failed": 1,
            "total_latency_ms": 0,
            "avg_latency_ms": None,
            "recent_failure_class": None,
        },
        "doubao-seed": {
            "requests": 2,
            "succeeded": 2,
            "failed": 0,
            "total_latency_ms": 0,
            "avg_latency_ms": None,
            "recent_failure_class": None,
        },
    }
    assert payload["ai"]["tokens"]["by_provider"] == {
        "openai": 140,
        "volcengine": 60,
    }
    assert payload["ai"]["tokens"]["by_model"] == {
        "gpt-4o-mini": 140,
        "doubao-seed": 60,
    }
    assert payload["history"]["rows"][0]["ai"]["state_counts"]["succeeded"] == 5
    assert payload["history"]["rows"][0]["ai"]["failure_counts"] == {"timeout": 1}


@pytest.mark.asyncio
async def test_fetch_llm_task_stats_history_fallback_ignores_images_only_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仅有画画 images 的 live ai 不应挡住历史 LLM token / state_counts 回退。"""
    bot_snapshot = {
        "source": "bot",
        "day_key": "2026-06-20",
        "updated_at": 1.0,
        "by_task": {},
        "totals": {},
    }
    historical_ai = {
        "source": "bot",
        "day_key": "2026-06-19",
        "state_counts": {"queued": 0, "running": 0, "succeeded": 5, "failed": 1},
        "tokens": {
            "source": "bot",
            "day_key": "2026-06-19",
            "prompt_tokens": 100,
            "completion_tokens": 100,
            "total_tokens": 200,
            "by_provider": {"openai": 200},
            "by_model": {"gpt-4o-mini": 200},
        },
    }
    _patch_bot_snapshots(monkeypatch, bot_snapshot)
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.today_key",
        lambda: "2026-06-20",
        raising=False,
    )
    _patch_bot_tokens(monkeypatch, {})
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.load_llm_daily_stats_range",
        lambda *, start_day, end_day: ([{"date": "2026-06-19", "bot": None, "ai": historical_ai}], start_day, end_day),
    )

    images_only = {
        "day_key": "2026-06-20",
        "ok_count": 2,
        "fail_count": 0,
        "image_count": 2,
        "cost_total": 0.0,
        "by_gateway": {},
        "by_provider": {"p1": {"ok_count": 2, "fail_count": 0, "image_count": 2, "cost_total": 0.0}},
        "by_model": {"gpt-image-1": {"ok_count": 2, "fail_count": 0, "image_count": 2, "cost_total": 0.0}},
    }
    monkeypatch.setattr(
        "pallas_plugin_draw.draw_stats_store.flush_draw_stats_sync",
        lambda: None,
        raising=False,
    )
    monkeypatch.setattr(
        "pallas_plugin_draw.draw_stats_store.draw_stats_snapshot",
        lambda include_persisted=True: images_only,
        raising=False,
    )
    monkeypatch.setattr(
        "pallas_plugin_draw.draw_stats_store.cluster_draw_stats_snapshot",
        lambda **kwargs: images_only,
        raising=False,
    )

    payload = await fetch_llm_task_stats(start="2026-06-19", end="2026-06-20")

    assert payload["ai"]["state_counts"]["succeeded"] == 5
    assert payload["ai"]["tokens"]["total_tokens"] == 200
    assert payload["ai"]["images"]["ok_count"] == 2
    assert payload["ai"]["images"]["image_count"] == 2
