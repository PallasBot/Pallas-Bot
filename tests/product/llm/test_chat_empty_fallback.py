from __future__ import annotations

from pallas.product.llm.chat_empty_fallback import (
    QUERY_EMPTY_FALLBACK,
    QUERY_FAILED_FALLBACK,
    QUERY_NO_RESULT_FALLBACK,
    resolve_llm_chat_empty_fallback,
)


def _task(trace: dict[str, int]) -> dict[str, object]:
    return {
        "task_type": "llm_chat",
        "speak_trigger": "to_me",
        "agent_trace": trace,
    }


def test_query_empty_fallback_is_visible_after_successful_lookup() -> None:
    assert (
        resolve_llm_chat_empty_fallback(
            _task({"successful_query_call_count": 1, "query_tool_hit_count": 1}),
            "",
            suppress_empty_fallback=True,
        )
        == QUERY_EMPTY_FALLBACK
    )


def test_query_empty_fallback_distinguishes_no_result() -> None:
    assert (
        resolve_llm_chat_empty_fallback(
            _task({"successful_query_call_count": 1, "query_tool_empty_count": 1}),
            "",
        )
        == QUERY_NO_RESULT_FALLBACK
    )


def test_query_empty_fallback_distinguishes_tool_failure() -> None:
    assert (
        resolve_llm_chat_empty_fallback(
            _task({"query_tool_failed_count": 1}),
            "",
        )
        == QUERY_FAILED_FALLBACK
    )
