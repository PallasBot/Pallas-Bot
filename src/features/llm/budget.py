"""LLM 上下文字符预算：按 system + messages 总量裁剪历史。"""

from __future__ import annotations

from .models import ChatCompletionMessage


def estimate_prompt_chars(system_prompt: str, messages: list[ChatCompletionMessage]) -> int:
    total = len(system_prompt.strip())
    for item in messages:
        total += len(item.content)
    return total


def trim_messages_to_char_budget(
    messages: list[ChatCompletionMessage],
    *,
    system_prompt: str,
    budget_chars: int,
) -> list[ChatCompletionMessage]:
    if budget_chars <= 0 or not messages:
        return list(messages)
    kept = list(messages)
    while len(kept) > 1 and estimate_prompt_chars(system_prompt, kept) > budget_chars:
        kept.pop(0)
    if len(kept) == 1 and estimate_prompt_chars(system_prompt, kept) > budget_chars:
        content = kept[0].content
        overhead = estimate_prompt_chars(system_prompt, [])
        room = max(64, budget_chars - overhead)
        if len(content) > room:
            kept[0] = ChatCompletionMessage(role=kept[0].role, content=content[:room])
    return kept
