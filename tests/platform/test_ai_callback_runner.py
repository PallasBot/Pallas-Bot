from __future__ import annotations

import subprocess
import sys
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile
from nonebot.adapters.onebot.v11.exception import NetworkError

from pallas.core.platform.ai_callback import runner as ai_callback_runner
from pallas.core.platform.ai_callback.handlers import should_suppress_llm_duplicate_reply
from pallas.core.platform.ai_callback.task_types import (
    DRAW_IMAGE_TASK_TYPE,
    LLM_CHAT_TASK_TYPE,
)
from pallas.product.llm import delivery as llm_delivery
from pallas.product.llm.config import LlmConfig


@pytest.fixture(autouse=True)
def allow_enabled_llm_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LlmConfig(llm_chat_enabled=True)
    monkeypatch.setattr(llm_delivery, "get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.availability.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)

    async def scope_enabled(_bot_id, _group_id):
        return False

    monkeypatch.setattr("pallas.product.llm.availability.llm_plugin_disabled_for_scope", scope_enabled)


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
async def test_run_ai_callback_uses_redis_claim_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(return_value={"bot_id": "111", "group_id": 222}),
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
async def test_llm_delivery_skips_summary_writeback_when_policy_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """历史 delivery 算法测试：自研 agent 已退役，run_ai_callback 不再进入投递；
    这里直接调用 delivery 纯入口，明确按历史语义验证摘要写回策略。"""
    from pallas.product.llm import availability

    async def _open_gate(*_args, **_kwargs):
        return ""

    monkeypatch.setattr(availability, "llm_chat_exit_gate_reason", _open_gate)
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value={"message_id": 12})
    monkeypatch.setattr(llm_delivery, "append_llm_message", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_delivery, "can_write_runtime_state_summary", lambda: False)

    compact = AsyncMock()
    monkeypatch.setattr(llm_delivery, "compact_user_llm_history_with_summary", compact)

    task = {
        "bot_id": "111",
        "group_id": 222,
        "user_id": 333,
        "task_type": LLM_CHAT_TASK_TYPE,
        "user_text": "你好",
    }
    await llm_delivery.deliver_llm_callback_success(
        "task-summary-off",
        task,
        bot=bot,
        group_id=222,
        bot_id=111,
        bot_id_str="111",
        text="嗯",
        parsed_agent_trace=None,
        history_summary="此前聊过银灰",
        history_keep_messages=8,
    )

    compact.assert_not_awaited()


def _session_history_task(**overrides) -> dict:
    task = {
        "bot_id": "111",
        "group_id": 222,
        "user_id": 333,
        "task_type": LLM_CHAT_TASK_TYPE,
        "user_text": "牛牛在吗",
        "behavior_scene": "banter",
    }
    task.update(overrides)
    return task


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

    from pallas.product.llm.config import LlmConfig

    pytest.importorskip("pallas_plugin_draw")
    import pallas_plugin_draw.startup  # noqa: F401 — 注册 media task hooks

    from pallas.core.platform.ai_callback.task_types import DRAW_IMAGE_TASK_TYPE

    def draw_submodule(plugin_id: str, submodule: str):
        assert plugin_id == "draw"
        return importlib.import_module(f"pallas_plugin_draw.{submodule}")

    monkeypatch.setattr("pallas.core.platform.plugin_runtime.resolve.import_plugin_submodule", draw_submodule)
    disabled_llm = LlmConfig(llm_chat_enabled=False)
    monkeypatch.setattr("pallas.product.llm.delivery.get_llm_config", lambda: disabled_llm)
    monkeypatch.setattr("pallas.product.llm.availability.get_llm_config", lambda: disabled_llm)
    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: True)

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
async def test_run_ai_callback_sing_media_failure_is_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(return_value={"bot_id": "111", "group_id": 222, "task_type": "sing"}),
    )
    monkeypatch.setattr(ai_callback_runner, "send_group_voice", AsyncMock(return_value=False))

    upload = UploadFile(filename="sing.mp3", file=BytesIO(b"ID3"))

    result = await ai_callback_runner.run_ai_callback("sing-task-failed", status="success", file=upload)

    assert result == {"message": "failed"}


@pytest.mark.asyncio
async def test_run_ai_callback_draw_media_failure_is_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
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
    monkeypatch.setattr(ai_callback_runner, "send_group_image", AsyncMock(return_value=False))

    upload = UploadFile(filename="draw.png", file=BytesIO(b"PNG"))

    result = await ai_callback_runner.run_ai_callback("draw-task-failed", status="success", file=upload)

    assert result == {"message": "failed"}


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
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "2927116873",
                "group_id": 626266902,
                "user_id": 123456789,
                "task_type": "sing",
            }
        ),
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
async def test_resolve_callback_task_uses_redis_claim_authority(monkeypatch) -> None:
    from pallas.core.platform.shard.coord import ai_task_registry

    record = {
        "task_id": "sing-task-unified-restart",
        "bot_id": "2927116873",
        "group_id": 626266902,
        "user_id": 123456789,
        "task_type": "chat_drunk",
        "candidate_pool": ["第一条", "第二条"],
        "want_tts": True,
    }
    records = {record["task_id"]: dict(record)}

    monkeypatch.setattr("pallas.core.platform.coord.redis_settings.coord_redis_enabled", lambda: True)
    monkeypatch.setattr(ai_task_registry, "claim_ai_task_record", lambda task_id: records.pop(task_id, None))
    ai_callback_runner.TaskManager._tasks = {}

    result = await ai_callback_runner.resolve_callback_task("sing-task-unified-restart")

    assert result is not None
    assert result["bot_id"] == "2927116873"
    assert result["group_id"] == 626266902
    assert result["candidate_pool"] == ["第一条", "第二条"]
    assert result["want_tts"] is True
    assert await ai_callback_runner.resolve_callback_task("sing-task-unified-restart") is None


@pytest.mark.asyncio
async def test_resolve_callback_task_local_claim_is_one_shot(monkeypatch) -> None:
    import asyncio
    import time

    task = {
        "bot_id": "2927116873",
        "group_id": 626266902,
        "user_id": 123456789,
        "task_type": "sing",
        "start_time": time.time(),
    }
    remove_started = asyncio.Event()
    allow_remove = asyncio.Event()

    async def deferred_to_thread(function, *args):
        remove_started.set()
        await allow_remove.wait()
        return function(*args)

    monkeypatch.setattr("pallas.core.platform.coord.redis_settings.coord_redis_enabled", lambda: False)
    monkeypatch.setattr(
        "pallas.core.platform.shard.coord.ai_task_registry.remove_ai_task",
        lambda _task_id: None,
    )
    monkeypatch.setattr("pallas.core.foundation.config.asyncio.to_thread", deferred_to_thread)
    ai_callback_runner.TaskManager._tasks = {"sing-task-race": dict(task)}
    ai_callback_runner.TaskManager._terminal = {}
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

    with pytest.raises(HTTPException) as exc_info:
        await ai_callback_runner.run_ai_callback("task-dup-voice", status="success", text="ok")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_run_ai_callback_voice_delivery_invokes_media_task_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.ai_callback import media_task_hooks as hooks_mod

    seen: list[tuple] = []
    hooks_mod.register_media_task_hooks(
        "sing",
        on_success=lambda task, blob, gid: seen.append((task["task_type"], gid, len(blob))),
    )
    try:
        bot = MagicMock()
        bot.call_api = AsyncMock(return_value={"message_id": 12})
        monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
        monkeypatch.setattr(
            ai_callback_runner.TaskManager,
            "claim_task",
            AsyncMock(return_value={"bot_id": "111", "group_id": 222, "user_id": 333, "task_type": "sing"}),
        )
        file = MagicMock()
        file.read = AsyncMock(return_value=b"\xff\xf3\xc4" * 100)

        result = await ai_callback_runner.run_ai_callback("task-sing", status="success", file=file)

        assert result == {"message": "ok"}
        assert seen == [("sing", 222, 300)]
    finally:
        hooks_mod.clear_media_task_hooks_for_tests()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "failed"])
@pytest.mark.parametrize("task_type", ["llm_chat", "ollama", "chat", " LLM_CHAT ", "Chat", "OLLAMA"])
async def test_run_ai_callback_retired_task_is_terminal_ack_without_side_effects(
    monkeypatch: pytest.MonkeyPatch, status: str, task_type: str
) -> None:
    """旧聊天/RWKV 任务回调：claim 后返回 200 终态 ACK，不取 Bot、不发送、不写历史/反馈/遥测/媒体钩子。"""
    probes: list[str] = []

    def probe(name: str):
        def _record(*_args, **_kwargs):
            probes.append(name)

        return _record

    monkeypatch.setattr(ai_callback_runner, "get_bot", probe("get_bot"))
    monkeypatch.setattr(ai_callback_runner, "send_group_message", AsyncMock(side_effect=probe("send")))
    monkeypatch.setattr(ai_callback_runner, "send_group_image", AsyncMock(side_effect=probe("send_image")))
    monkeypatch.setattr(ai_callback_runner, "send_group_voice", AsyncMock(side_effect=probe("send_voice")))
    monkeypatch.setattr(ai_callback_runner, "failure_reply_for_task", probe("failure_reply"))
    monkeypatch.setattr(ai_callback_runner, "invoke_media_task_failure", probe("media_failure"))
    monkeypatch.setattr(ai_callback_runner, "invoke_media_task_success", probe("media_success"))
    monkeypatch.setattr(ai_callback_runner, "deliver_llm_callback_success", AsyncMock(side_effect=probe("delivery")))
    monkeypatch.setattr(ai_callback_runner, "track_llm_callback", probe("track"))
    monkeypatch.setattr(ai_callback_runner, "record_turn_event", probe("turn_event"))
    monkeypatch.setattr(llm_delivery, "append_llm_message", AsyncMock(side_effect=probe("history")))
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "claim_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "user_id": 333,
                "task_type": task_type,
                "user_text": "hi",
            }
        ),
    )

    result = await ai_callback_runner.run_ai_callback("task-retired", status=status, text="x")

    assert result == {"message": "ok", "status": "legacy_agent_retired"}
    assert probes == []
