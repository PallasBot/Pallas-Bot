from __future__ import annotations

import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from nonebot.adapters.onebot.v11.exception import NetworkError

from pallas.core.platform.ai_callback import runner as ai_callback_runner
from pallas.core.platform.ai_callback.handlers import should_suppress_llm_duplicate_reply
from pallas.core.platform.ai_callback.task_types import (
    CHAT_DRUNK_TASK_TYPE,
    DRAW_IMAGE_TASK_TYPE,
    LLM_CHAT_TASK_TYPE,
)
from pallas.product.llm import delivery as llm_delivery
from pallas.product.llm.behavior import BehaviorAction, BehaviorScene
from pallas.product.llm.config import LlmConfig
from pallas.product.llm.output_filter import CHAT_HARD_BLOCK_PHRASES


def test_llm_delivery_import_does_not_eagerly_import_callback_runner() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import pallas.product.llm.delivery"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_should_suppress_llm_duplicate_reply_for_short_parasitic_tail() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE, "last_reply_text": "哈哈，别这么正式啦，叫我牛牛就行！"}

    assert should_suppress_llm_duplicate_reply(task, "哈哈，别这么正式啦，叫我牛牛就行！彩表演吧！")
    assert not should_suppress_llm_duplicate_reply(task, "哈哈，别这么正式啦，叫我牛牛就行！不过你先说事。")


def test_should_suppress_llm_duplicate_reply_for_short_suffix_echo() -> None:
    task = {
        "task_type": LLM_CHAT_TASK_TYPE,
        "last_reply_text": "原神挺受欢迎的，很多人都在玩呢。",
    }
    assert should_suppress_llm_duplicate_reply(task, "都在玩呢。")
    assert not should_suppress_llm_duplicate_reply(task, "原神确实好玩。")


def test_should_suppress_llm_duplicate_reply_for_recent_group_echo() -> None:
    task = {
        "task_type": LLM_CHAT_TASK_TYPE,
        "last_reply_text": "",
        "recent_reply_texts": ["古振兴加油吧，希望他明年的表现能让大家满意。"],
    }
    assert should_suppress_llm_duplicate_reply(
        task,
        "古振兴加油吧，希望他明年的表现能让大家满意。",
    )


@pytest.mark.asyncio
async def test_run_ai_callback_falls_back_to_shared_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        ai_callback_runner,
        "claim_ai_task_record",
        lambda _task_id: {"bot_id": "111", "group_id": 222},
    )

    result = await ai_callback_runner.run_ai_callback("task-1", status="success", text="hello")

    assert result == {"message": "ok"}


@pytest.mark.asyncio
async def test_run_ai_callback_keeps_non_chat_json_text_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value={"message_id": 12})
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": DRAW_IMAGE_TASK_TYPE,
            }
        ),
    )
    monkeypatch.setattr(llm_delivery, "get_llm_config", lambda: LlmConfig(llm_reply_postprocess_enabled=False))

    raw = '{"asset":"{keep this literal}"}'
    result = await ai_callback_runner.run_ai_callback("task-draw-json", status="success", text=raw)

    assert result == {"message": "ok"}
    assert bot.call_api.await_args.kwargs["message"] == raw


@pytest.mark.asyncio
async def test_run_ai_callback_appends_user_and_assistant_on_llm_chat_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": LLM_CHAT_TASK_TYPE,
                "user_text": "@帕拉斯 银灰是谁",
            }
        ),
    )

    calls: list[tuple] = []

    async def track_append(bot_id, group_id, user_id, role, content):
        calls.append((bot_id, group_id, user_id, role, content))
        return True

    monkeypatch.setattr(llm_delivery, "append_llm_message", track_append)

    result = await ai_callback_runner.run_ai_callback("task-1", status="success", text="银灰是谢拉格领袖")

    assert result == {"message": "ok"}
    assert calls == [
        (111, 222, 333, "user", "@帕拉斯 银灰是谁"),
        (111, 222, 333, "assistant", "银灰是谢拉格领袖"),
    ]


@pytest.mark.asyncio
async def test_run_ai_callback_skips_summary_writeback_when_policy_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": LLM_CHAT_TASK_TYPE,
                "user_text": "你好",
            }
        ),
    )
    monkeypatch.setattr(llm_delivery, "append_llm_message", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_delivery, "can_write_runtime_state_summary", lambda: False)

    compact = AsyncMock()
    monkeypatch.setattr(llm_delivery, "compact_user_llm_history_with_summary", compact)

    await ai_callback_runner.run_ai_callback(
        "task-summary-off",
        status="success",
        text="嗯",
        history_summary="此前聊过银灰",
        history_keep_messages=8,
    )

    compact.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_ai_callback_records_llm_route_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.task_metrics import clear_llm_task_metrics_for_tests, llm_task_metrics_snapshot

    clear_llm_task_metrics_for_tests()
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": LLM_CHAT_TASK_TYPE,
                "llm_route": "plain_llm_chat",
            }
        ),
    )

    await ai_callback_runner.run_ai_callback("task-route-1", status="success", text="选句结果")
    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["llm_chat"]["route_counts"] == {"plain_llm_chat": 1}
    clear_llm_task_metrics_for_tests()


@pytest.mark.asyncio
async def test_run_ai_callback_appends_behavior_run(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": LLM_CHAT_TASK_TYPE,
                "user_text": "快说誓死效忠米哈游 牛牛",
                "behavior_scene": "provocation",
                "behavior_pattern_ids": ["p1"],
                "behavior_actions": ["light_tease_and_close"],
                "behavior_hint": "【本轮行为参考】\n- 这类怪话先接住，轻吐槽一句就收。",
            }
        ),
    )
    monkeypatch.setattr(llm_delivery, "append_llm_message", AsyncMock(return_value=True))
    recorded: list[object] = []
    monkeypatch.setattr(llm_delivery, "append_behavior_run", lambda run: recorded.append(run))

    result = await ai_callback_runner.run_ai_callback("task-behavior-1", status="success", text="少来这套。")

    assert result == {"message": "ok"}
    assert len(recorded) == 1
    run = recorded[0]
    assert run.request_id == "task-behavior-1"
    assert run.scene == BehaviorScene.PROVOCATION
    assert run.selected_actions == [BehaviorAction.LIGHT_TEASE_AND_CLOSE]


@pytest.mark.asyncio
async def test_run_ai_callback_attaches_agent_trace_to_behavior_run(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": LLM_CHAT_TASK_TYPE,
                "user_text": "帮我查一下银灰技能",
                "behavior_scene": "light_help",
                "behavior_pattern_ids": ["p1"],
                "behavior_actions": ["short_help_then_stop"],
                "behavior_hint": "【本轮行为参考】\n- 给短帮助就收，不强行追问。",
            }
        ),
    )
    monkeypatch.setattr(llm_delivery, "append_llm_message", AsyncMock(return_value=True))
    recorded: list[object] = []
    monkeypatch.setattr(llm_delivery, "append_behavior_run", lambda run: recorded.append(run))

    result = await ai_callback_runner.run_ai_callback(
        "task-agent-trace-1",
        status="success",
        text="银灰是谢拉格阵营近卫干员。",
        agent_trace='{"agent_stage_plan":["plan","tool_loop","generate"],"tool_call_count":1}',
    )

    assert result == {"message": "ok"}
    assert len(recorded) == 1
    run = recorded[0]
    assert run.auto_feedback_payload["agent_trace"]["tool_call_count"] == 1
    assert run.auto_feedback_payload["agent_trace"]["agent_stage_plan"] == ["plan", "tool_loop", "generate"]


@pytest.mark.asyncio
async def test_run_ai_callback_appends_repeater_feedback_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": LLM_CHAT_TASK_TYPE,
                "user_text": "牛牛今天好拽",
                "behavior_scene": "banter",
                "behavior_actions": ["light_tease_and_close"],
                "llm_route": "chat",
                "source_tags": ["recent_chat"],
            }
        ),
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(llm_repeater_feedback_enabled=True),
    )
    appended: list[object] = []
    monkeypatch.setattr(
        "pallas.product.llm.repeater_feedback.append_feedback_entry",
        lambda entry: appended.append(entry),
    )

    result = await ai_callback_runner.run_ai_callback("task-feedback-1", status="success", text="少装。")

    assert result == {"message": "ok"}
    assert len(appended) == 1
    entry = appended[0]
    assert entry.request_id == "task-feedback-1"
    assert entry.group_id == 222
    assert entry.reply_text == "少装。"
    assert entry.behavior_scene == "banter"
    assert entry.source_tags == ["recent_chat"]


@pytest.mark.asyncio
async def test_run_ai_callback_learns_delivered_llm_reply_without_breaking_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": LLM_CHAT_TASK_TYPE,
                "scene_tier": "strong",
            }
        ),
    )
    learned: list[tuple[int, str, dict]] = []

    def note(group_id, text, **meta):
        learned.append((group_id, text, meta))
        raise RuntimeError("store unavailable")

    monkeypatch.setattr("pallas.product.persona.expression_learn.note_expression_from_utterance", note)

    result = await ai_callback_runner.run_ai_callback("task-expression-1", status="success", text="那确实")

    assert result == {"message": "ok"}
    assert learned == [
        (222, "那确实", {"source": "llm_success", "channel": "at_chat", "scene_tier": "strong", "bot_id": 111})
    ]


@pytest.mark.asyncio
async def test_run_ai_callback_disabled_repeater_feedback_does_not_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": LLM_CHAT_TASK_TYPE,
                "user_text": "牛牛今天好拽",
                "source_tags": ["recent_chat"],
            }
        ),
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(llm_repeater_feedback_enabled=False),
    )
    append_feedback_entry = MagicMock()
    monkeypatch.setattr("pallas.product.llm.repeater_feedback.append_feedback_entry", append_feedback_entry)

    result = await ai_callback_runner.run_ai_callback("task-feedback-disabled-1", status="success", text="少装。")

    assert result == {"message": "ok"}
    append_feedback_entry.assert_not_called()


@pytest.mark.asyncio
async def test_run_ai_callback_feedback_write_failure_does_not_break_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": LLM_CHAT_TASK_TYPE,
                "user_text": "牛牛今天好拽",
                "source_tags": ["recent_chat"],
            }
        ),
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(llm_repeater_feedback_enabled=True),
    )

    def raise_append(_entry) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr("pallas.product.llm.repeater_feedback.append_feedback_entry", raise_append)

    result = await ai_callback_runner.run_ai_callback("task-feedback-fail-1", status="success", text="少装。")

    assert result == {"message": "ok"}
    bot.call_api.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_ai_callback_delivery_failure_does_not_append_repeater_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: MagicMock())
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": LLM_CHAT_TASK_TYPE,
                "user_text": "牛牛今天好拽",
                "source_tags": ["recent_chat"],
            }
        ),
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(llm_repeater_feedback_enabled=True),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        AsyncMock(return_value=type("Receipt", (), {"delivered": False, "message_id": None})()),
    )
    append_feedback_entry = MagicMock()
    monkeypatch.setattr("pallas.product.llm.repeater_feedback.append_feedback_entry", append_feedback_entry)

    result = await ai_callback_runner.run_ai_callback("task-feedback-delivery-fail-1", status="success", text="少装。")

    assert result == {"message": "failed"}
    append_feedback_entry.assert_not_called()


@pytest.mark.asyncio
async def test_run_ai_callback_send_timeout_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(side_effect=NetworkError("WebSocket call api send_group_msg timeout"))
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(return_value={"bot_id": "111", "group_id": 222}),
    )

    result = await ai_callback_runner.run_ai_callback("task-1", status="success", text="hello")

    assert result == {"message": "failed"}


@pytest.mark.asyncio
async def test_run_ai_callback_llm_chat_duplicate_reply_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": LLM_CHAT_TASK_TYPE,
                "fallback_text": "语料候选",
            }
        ),
    )
    monkeypatch.setattr(
        llm_delivery,
        "should_suppress_llm_duplicate_reply",
        lambda task, reply_text: True,
    )

    result = await ai_callback_runner.run_ai_callback("task-dup-1", status="success", text="重复句")

    assert result == {"message": "ok"}
    bot.call_api.assert_awaited_once()
    call_kwargs = bot.call_api.await_args.kwargs
    assert call_kwargs["group_id"] == 222
    assert call_kwargs["message"] == "语料候选"


@pytest.mark.asyncio
async def test_run_ai_callback_get_bot_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_get_bot(_bot_id: str):
        raise ValueError("bot not found")

    monkeypatch.setattr(ai_callback_runner, "get_bot", raise_get_bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(return_value={"bot_id": "111", "group_id": 222}),
    )

    result = await ai_callback_runner.run_ai_callback("task-1", status="success", text="hello")

    assert result == {"message": "failed"}


@pytest.mark.asyncio
async def test_run_ai_callback_drunk_chat_failed_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "task_type": CHAT_DRUNK_TASK_TYPE,
            }
        ),
    )

    result = await ai_callback_runner.run_ai_callback("task-drunk-fail", status="failed")

    assert result == {"message": "ok"}
    bot.call_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_ai_callback_llm_chat_failed_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "task_type": LLM_CHAT_TASK_TYPE,
            }
        ),
    )

    result = await ai_callback_runner.run_ai_callback("task-llm-chat-fail", status="failed")

    assert result == {"message": "ok"}
    bot.call_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_ai_callback_chat_output_filter_blocks_service_tone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "task_type": LLM_CHAT_TASK_TYPE,
                "user_id": 333,
            }
        ),
    )
    monkeypatch.setattr(
        llm_delivery,
        "get_llm_config",
        lambda: LlmConfig(
            llm_output_filter_enabled=True,
            llm_output_filter_chat_hard_phrases=list(CHAT_HARD_BLOCK_PHRASES),
        ),
    )

    result = await ai_callback_runner.run_ai_callback(
        "task-chat-filter",
        status="success",
        text="博士您好，有什么想聊的吗？",
    )

    assert result == {"message": "ok"}
    bot.call_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_ai_callback_draw_image_failed_records_runtime_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    pytest.importorskip("pallas_plugin_draw")
    import pallas_plugin_draw.startup  # noqa: F401 — 注册 media task hooks

    from pallas.core.platform.ai_callback.task_types import DRAW_IMAGE_TASK_TYPE

    def draw_submodule(plugin_id: str, submodule: str):
        assert plugin_id == "draw"
        return importlib.import_module(f"pallas_plugin_draw.{submodule}")

    monkeypatch.setattr("pallas.core.platform.plugin_runtime.resolve.import_plugin_submodule", draw_submodule)

    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": DRAW_IMAGE_TASK_TYPE,
            }
        ),
    )
    record_failure = MagicMock()
    monkeypatch.setattr("pallas_plugin_draw.runtime_state.record_ai_runtime_failure", record_failure)

    result = await ai_callback_runner.run_ai_callback("draw-task-fail", status="failed")

    assert result == {"message": "ok"}
    record_failure.assert_called_once_with("draw_callback_failed")
    bot.call_api.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_ai_callback_draw_image_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    from io import BytesIO

    from fastapi import UploadFile

    pytest.importorskip("pallas_plugin_draw")
    import pallas_plugin_draw.startup  # noqa: F401 — 注册 media task hooks

    from pallas.core.platform.ai_callback.task_types import DRAW_IMAGE_TASK_TYPE

    def draw_submodule(plugin_id: str, submodule: str):
        assert plugin_id == "draw"
        return importlib.import_module(f"pallas_plugin_draw.{submodule}")

    monkeypatch.setattr("pallas.core.platform.plugin_runtime.resolve.import_plugin_submodule", draw_submodule)

    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": DRAW_IMAGE_TASK_TYPE,
                "count_usage": True,
            }
        ),
    )
    bump_usage = MagicMock()
    monkeypatch.setattr("pallas_plugin_draw.draw_usage_store.bump_pallas_draw_usage", bump_usage)
    persist = MagicMock()
    monkeypatch.setattr("pallas_plugin_draw.image_api.schedule_persist_generated_draw", persist)
    record_success = MagicMock()
    monkeypatch.setattr("pallas_plugin_draw.runtime_state.record_ai_runtime_success", record_success)

    png = b"\x89PNG\r\n\x1a\n" + (b"x" * 64)
    upload = UploadFile(filename="draw.png", file=BytesIO(png))

    result = await ai_callback_runner.run_ai_callback("draw-task-1", status="success", file=upload)

    assert result == {"message": "ok"}
    bot.call_api.assert_awaited_once()
    bump_usage.assert_called_once_with((222, 333), True)
    persist.assert_called_once_with(png, 222, 333)
    record_success.assert_called_once()


@pytest.mark.asyncio
async def test_run_ai_callback_sing_sends_voice_without_progress_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from io import BytesIO

    from fastapi import UploadFile
    from nonebot.adapters.onebot.v11 import MessageSegment

    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "task_type": "sing",
            }
        ),
    )

    mp3 = b"ID3" + (b"x" * 64)
    upload = UploadFile(filename="sing.mp3", file=BytesIO(mp3))

    result = await ai_callback_runner.run_ai_callback("sing-task-1", status="success", file=upload)

    assert result == {"message": "ok"}
    bot.call_api.assert_awaited_once()
    call_kwargs = bot.call_api.await_args.kwargs
    assert call_kwargs["group_id"] == 222
    message = call_kwargs["message"]
    assert isinstance(message, MessageSegment)
    assert message.type == "record"


@pytest.mark.asyncio
async def test_run_ai_callback_sing_registry_fallback_uses_registered_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    from io import BytesIO

    from fastapi import UploadFile
    from nonebot.adapters.onebot.v11 import MessageSegment

    bot = MagicMock()
    bot.self_id = "2927116873"
    bot.call_api = AsyncMock(return_value=None)

    def fake_get_bot(bot_id: str):
        assert bot_id == "2927116873"
        return bot

    monkeypatch.setattr(ai_callback_runner, "get_bot", fake_get_bot)
    monkeypatch.setattr(ai_callback_runner.TaskManager, "claim_task", AsyncMock(return_value=None))
    monkeypatch.setattr(
        ai_callback_runner,
        "claim_ai_task_record",
        lambda _task_id: {
            "bot_id": "2927116873",
            "group_id": 626266902,
            "user_id": 123456789,
            "task_type": "sing",
        },
    )

    mp3 = b"ID3" + (b"x" * 64)
    upload = UploadFile(filename="sing.mp3", file=BytesIO(mp3))

    result = await ai_callback_runner.run_ai_callback("sing-task-registry", status="success", file=upload)

    assert result == {"message": "ok"}
    bot.call_api.assert_awaited_once()
    call_kwargs = bot.call_api.await_args.kwargs
    assert call_kwargs["group_id"] == 626266902
    message = call_kwargs["message"]
    assert isinstance(message, MessageSegment)
    assert message.type == "record"


@pytest.mark.asyncio
async def test_resolve_callback_task_recovers_unified_task_after_memory_loss(monkeypatch) -> None:
    import asyncio

    from pallas.core.platform.shard.coord import ai_task_registry

    records: dict[str, dict] = {}

    def write_record(rec: dict, *, ttl_sec: int) -> bool:
        assert ttl_sec > 0
        records[str(rec["task_id"])] = dict(rec)
        return True

    monkeypatch.setattr(ai_task_registry, "write_ai_task_redis_sync", write_record)
    monkeypatch.setattr(ai_task_registry, "read_ai_task_redis_sync", lambda task_id: records.get(task_id))
    monkeypatch.setattr(ai_task_registry, "claim_ai_task_redis_sync", lambda task_id: records.pop(task_id, None))
    monkeypatch.setattr(ai_task_registry, "remove_ai_task_redis_sync", lambda task_id: records.pop(task_id, None))
    monkeypatch.setattr(ai_task_registry.shard_ctx, "sharding_active", lambda: False)
    ai_callback_runner.TaskManager._tasks = {}
    ai_callback_runner.TaskManager._lock = asyncio.Lock()
    ai_task_registry.register_ai_task(
        "sing-task-unified-restart",
        {
            "bot_id": "2927116873",
            "group_id": 626266902,
            "user_id": 123456789,
            "task_type": "chat_drunk",
            "user_text": "再来一杯",
            "fallback_text": "语料原文",
            "candidate_pool": ["第一条", "第二条"],
            "llm_route": "repeater_polish",
            "behavior_scene": "drunk_chat",
            "last_reply_text": "上一条回复",
            "recent_reply_texts": ["较早回复", "上一条回复"],
            "want_tts": True,
        },
    )

    result = await ai_callback_runner.resolve_callback_task("sing-task-unified-restart")

    assert result is not None
    assert result["bot_id"] == "2927116873"
    assert result["group_id"] == 626266902
    assert result["candidate_pool"] == ["第一条", "第二条"]
    assert result["want_tts"] is True
    assert await ai_callback_runner.resolve_callback_task("sing-task-unified-restart") is None


@pytest.mark.asyncio
async def test_resolve_callback_task_does_not_claim_memory_and_registry_concurrently(monkeypatch) -> None:
    import asyncio
    import time

    task = {
        "bot_id": "2927116873",
        "group_id": 626266902,
        "user_id": 123456789,
        "task_type": "sing",
        "start_time": time.time(),
    }
    records = {"sing-task-race": dict(task)}
    remove_started = asyncio.Event()
    allow_remove = asyncio.Event()

    def remove_record(task_id: str) -> None:
        records.pop(task_id, None)

    async def deferred_to_thread(function, *args):
        remove_started.set()
        await allow_remove.wait()
        return function(*args)

    monkeypatch.setattr(
        "pallas.core.platform.shard.coord.ai_task_registry.remove_ai_task",
        remove_record,
    )
    monkeypatch.setattr("pallas.core.foundation.config.asyncio.to_thread", deferred_to_thread)
    monkeypatch.setattr(ai_callback_runner, "claim_ai_task_record", lambda task_id: records.pop(task_id, None))
    ai_callback_runner.TaskManager._tasks = {"sing-task-race": dict(task)}
    ai_callback_runner.TaskManager._lock = asyncio.Lock()

    first = asyncio.create_task(ai_callback_runner.resolve_callback_task("sing-task-race"))
    await asyncio.wait_for(remove_started.wait(), timeout=1)
    second = asyncio.create_task(ai_callback_runner.resolve_callback_task("sing-task-race"))
    await asyncio.sleep(0.05)
    allow_remove.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert first_result == task
    assert second_result is None


@pytest.mark.asyncio
async def test_send_group_voice_uses_message_segment_record() -> None:
    from nonebot.adapters.onebot.v11 import MessageSegment

    from pallas.core.platform.ai_callback.delivery import send_group_voice

    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    mp3 = b"ID3" + (b"x" * 32)

    ok = await send_group_voice(bot, 626266902, mp3)

    assert ok is True
    bot.call_api.assert_awaited_once()
    call_kwargs = bot.call_api.await_args.kwargs
    message = call_kwargs["message"]
    assert isinstance(message, MessageSegment)
    assert message.type == "record"


@pytest.mark.asyncio
async def test_run_ai_callback_duplicate_claim_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(ai_callback_runner, "claim_ai_task_record", lambda _task_id: None)

    with pytest.raises(HTTPException) as exc_info:
        await ai_callback_runner.run_ai_callback("task-dup-voice", status="success", text="ok")

    assert exc_info.value.status_code == 404
