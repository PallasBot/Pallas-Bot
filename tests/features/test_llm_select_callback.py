from __future__ import annotations

from pallas.core.platform.ai_callback.handlers import failure_reply_for_task
from pallas.core.platform.ai_callback.task_types import (
    REPEATER_POLISH_LITE_TASK_TYPE,
    REPEATER_POLISH_TASK_TYPE,
    REPEATER_SELECT_TASK_TYPE,
)
from pallas.product.llm.select import resolve_select_callback_text


def test_failure_reply_for_select_is_silent_even_with_fallback() -> None:
    reply = failure_reply_for_task({
        "task_type": REPEATER_SELECT_TASK_TYPE,
        "fallback_text": "摸摸",
    })
    assert reply is None


def test_failure_reply_for_select_silent_without_fallback() -> None:
    reply = failure_reply_for_task({"task_type": REPEATER_SELECT_TASK_TYPE})
    assert reply is None


def test_failure_reply_for_polish_is_silent_even_with_fallback() -> None:
    reply = failure_reply_for_task({
        "task_type": REPEATER_POLISH_TASK_TYPE,
        "fallback_text": "语料原文",
    })
    assert reply is None


def test_failure_reply_for_polish_lite_is_silent_even_with_fallback() -> None:
    reply = failure_reply_for_task({
        "task_type": REPEATER_POLISH_LITE_TASK_TYPE,
        "fallback_text": "语料原文",
    })
    assert reply is None


def test_resolve_select_callback_text_maps_index() -> None:
    pool = ["a", "b", "c"]
    assert resolve_select_callback_text("2", pool, "a") == "b"
    assert resolve_select_callback_text("0", pool, "a") == "a"
