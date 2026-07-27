"""续聊软窗口与空回复兜底。"""

from __future__ import annotations

from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm.chat_empty_fallback import resolve_llm_chat_empty_fallback
from pallas.product.llm.followup_window import (
    clear_followup_window_state,
    in_followup_window,
    note_hard_speak_trigger,
)
from pallas.product.llm.speak_perception import (
    clear_speak_perception_state,
    evaluate_speak_perception,
)


def test_followup_window_hard_then_soft() -> None:
    clear_followup_window_state()
    note_hard_speak_trigger(7, 1, 9, window_seconds=30, max_total_seconds=120, now=1000.0)
    assert in_followup_window(7, 1, 9, window_seconds=30, max_total_seconds=120, now=1010.0)
    assert not in_followup_window(7, 1, 8, window_seconds=30, max_total_seconds=120, now=1010.0)
    assert not in_followup_window(7, 1, 9, window_seconds=30, max_total_seconds=120, now=1040.0)


def test_followup_isolated_per_bot() -> None:
    clear_followup_window_state()
    note_hard_speak_trigger(2357682124, 1, 9, window_seconds=30, max_total_seconds=120, now=1000.0)
    assert in_followup_window(2357682124, 1, 9, window_seconds=30, max_total_seconds=120, now=1010.0)
    assert not in_followup_window(3129723001, 1, 9, window_seconds=30, max_total_seconds=120, now=1010.0)


def test_followup_soft_does_not_extend_by_itself() -> None:
    clear_followup_window_state()
    note_hard_speak_trigger(7, 2, 9, window_seconds=20, max_total_seconds=100, now=1000.0)
    # 软触发不调用 note_hard；窗口仍按 1000 起算
    assert in_followup_window(7, 2, 9, window_seconds=20, max_total_seconds=100, now=1015.0)
    assert not in_followup_window(7, 2, 9, window_seconds=20, max_total_seconds=100, now=1025.0)


def test_followup_max_total_ceiling() -> None:
    clear_followup_window_state()
    note_hard_speak_trigger(7, 3, 9, window_seconds=60, max_total_seconds=50, now=1000.0)
    note_hard_speak_trigger(7, 3, 9, window_seconds=60, max_total_seconds=50, now=1030.0)
    assert not in_followup_window(7, 3, 9, window_seconds=60, max_total_seconds=50, now=1055.0)


def test_evaluate_followup_before_ambient() -> None:
    clear_speak_perception_state()
    d = evaluate_speak_perception(
        plain_text="然后呢",
        aliases=["牛牛"],
        is_to_me=False,
        bot_id=1,
        mention_enabled=True,
        ambient_enabled=False,
        followup_active=True,
    )
    assert d.should_speak
    assert d.reason == "followup"


def test_empty_fallback_for_hard_trigger() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE, "speak_trigger": "mention", "fallback_text": ""}
    assert resolve_llm_chat_empty_fallback(task, "") == "咋了"
    assert resolve_llm_chat_empty_fallback(task, "  你好  ") == "你好"


def test_empty_fallback_uses_corpus_fallback() -> None:
    task = {
        "task_type": LLM_CHAT_TASK_TYPE,
        "speak_trigger": "to_me",
        "fallback_text": "在呢",
    }
    assert resolve_llm_chat_empty_fallback(task, "") == "在呢"


def test_empty_fallback_replaces_filler_only_corpus_fallback() -> None:
    task = {
        "task_type": LLM_CHAT_TASK_TYPE,
        "speak_trigger": "to_me",
        "fallback_text": "嗯？",
    }
    assert resolve_llm_chat_empty_fallback(task, "") == "咋了"


def test_empty_fallback_silent_for_ambient() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE, "speak_trigger": "ambient"}
    assert resolve_llm_chat_empty_fallback(task, "") == ""


def test_empty_fallback_silent_after_tool_calls() -> None:
    task = {
        "task_type": LLM_CHAT_TASK_TYPE,
        "speak_trigger": "mention",
        "fallback_text": "在呢",
        "agent_trace": {"tool_call_count": 1},
    }
    assert resolve_llm_chat_empty_fallback(task, "") == ""
    assert resolve_llm_chat_empty_fallback(task, "房开了") == "房开了"
