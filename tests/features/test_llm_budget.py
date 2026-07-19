from __future__ import annotations

from pallas.product.llm.budget import estimate_prompt_chars, trim_messages_to_char_budget
from pallas.product.llm.models import ChatCompletionMessage


def test_trim_messages_drops_oldest_first() -> None:
    messages = [
        ChatCompletionMessage(role="user", content="a" * 100),
        ChatCompletionMessage(role="assistant", content="b" * 100),
        ChatCompletionMessage(role="user", content="current"),
    ]
    trimmed = trim_messages_to_char_budget(
        messages,
        system_prompt="sys",
        budget_chars=150,
    )
    assert len(trimmed) == 2
    assert trimmed[-1].content == "current"
    assert estimate_prompt_chars("sys", trimmed) <= 220


def test_trim_messages_keeps_single_turn_when_budget_tight() -> None:
    messages = [ChatCompletionMessage(role="user", content="x" * 500)]
    trimmed = trim_messages_to_char_budget(
        messages,
        system_prompt="system",
        budget_chars=120,
    )
    assert len(trimmed) == 1
    assert len(trimmed[0].content) <= 120 - len("system")
