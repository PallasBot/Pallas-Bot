from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.product.llm.model_admin import fetch_llm_task_stats


@pytest.mark.asyncio
async def test_fetch_llm_task_stats_treats_token_only_ai_snapshot_as_collecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_snapshot = {
        "source": "bot",
        "day_key": "2026-06-18",
        "updated_at": 1.0,
        "by_task": {},
        "totals": {},
    }
    ai_snapshot = {
        "source": "ai",
        "day_key": "2026-06-18",
        "tokens": {
            "prompt_tokens": 123,
            "completion_tokens": 77,
            "total_tokens": 200,
        },
        "totals": {"task_ok": 4, "task_fail": 1},
    }
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = ai_snapshot

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
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.today_key",
        lambda: "2026-06-18",
        raising=False,
    )
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.HTTPXClient.get",
        AsyncMock(return_value=response),
    )
    written: list[tuple[str, str, dict[str, object]]] = []
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.write_llm_daily_stats_side",
        lambda day, side, snapshot: written.append((day, side, snapshot)),
    )
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.load_llm_daily_stats_range",
        lambda *, start_day, end_day: ([], start_day, end_day),
    )

    payload = await fetch_llm_task_stats(start="2026-06-18", end="2026-06-18")

    assert payload["ai_reachable"] is True
    assert payload["persistence"]["ai_collecting"] is True
    assert payload["ai"]["tokens"]["total_tokens"] == 200
    assert payload["history"]["rows"][0]["ai"]["tokens"]["prompt_tokens"] == 123
    assert written[0][0] == "2026-06-18"
    assert written[0][1] == "ai"
    assert written[0][2]["reachable"] is True


@pytest.mark.asyncio
async def test_fetch_llm_task_stats_normalizes_ai_runtime_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_snapshot = {
        "source": "bot",
        "day_key": "2026-06-18",
        "updated_at": 1.0,
        "by_task": {},
        "totals": {},
    }
    ai_snapshot = {
        "source": "ai",
        "day_key": "2026-06-18",
        "by_task": {"llm_chat": {"task_ok": 2}},
        "totals": {"task_ok": 2},
        "tokens": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = ai_snapshot

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
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.today_key",
        lambda: "2026-06-18",
        raising=False,
    )
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.HTTPXClient.get",
        AsyncMock(return_value=response),
    )
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.write_llm_daily_stats_side",
        lambda day, side, snapshot: None,
    )
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.load_llm_daily_stats_range",
        lambda *, start_day, end_day: ([], start_day, end_day),
    )

    payload = await fetch_llm_task_stats(start="2026-06-18", end="2026-06-18")

    assert payload["ai"]["state_counts"] == {
        "queued": 0,
        "running": 0,
        "succeeded": 2,
        "failed": 0,
    }
    assert payload["ai"]["failure_counts"] == {}
    assert payload["ai"]["provider_stats"] == {}
    assert payload["ai"]["model_stats"] == {}
    assert payload["ai"]["tokens"]["by_provider"] == {}
    assert payload["ai"]["tokens"]["by_model"] == {}


@pytest.mark.asyncio
async def test_fetch_llm_task_stats_falls_back_to_latest_history_when_ai_unreachable(
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
        "source": "ai",
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
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.today_key",
        lambda: "2026-06-20",
        raising=False,
    )
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.HTTPXClient.get",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.write_llm_daily_stats_side",
        lambda day, side, snapshot: None,
    )
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.load_llm_daily_stats_range",
        lambda *, start_day, end_day: ([{"date": "2026-06-19", "bot": None, "ai": historical_ai}], start_day, end_day),
    )

    payload = await fetch_llm_task_stats(start="2026-06-19", end="2026-06-20")

    assert payload["ai_reachable"] is False
    assert payload["ai"]["state_counts"] == {
        "queued": 0,
        "running": 0,
        "succeeded": 5,
        "failed": 1,
    }
    assert payload["ai"]["failure_counts"] == {"timeout": 1}
    assert payload["ai"]["provider_stats"] == {
        "openai": {"ok": 3, "fail": 1},
        "volcengine": {"ok": 2, "fail": 0},
    }
    assert payload["ai"]["model_stats"] == {
        "gpt-4o-mini": {"ok": 3, "fail": 1},
        "doubao-seed": {"ok": 2, "fail": 0},
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
