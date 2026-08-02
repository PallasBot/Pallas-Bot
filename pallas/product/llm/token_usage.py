"""从 provider 响应中提取 token usage（含 prompt cache）。"""

from __future__ import annotations

from typing import Any


def usage_from_local_chat_response(data: dict[str, Any]) -> tuple[int, int, int, int]:
    """Ollama 风格：prompt_eval_count / eval_count；无 cache。"""
    prompt = int(data.get("prompt_eval_count") or 0)
    completion = int(data.get("eval_count") or 0)
    return max(0, prompt), max(0, completion), 0, 0


def _cache_from_token_details(details: object) -> tuple[int, int]:
    """从 prompt/input_tokens_details 取 cache_read / cache_write。"""
    if not isinstance(details, dict):
        return 0, 0
    cache_read = int(
        details.get("cached_tokens") or details.get("cache_read_tokens") or details.get("cache_read_input_tokens") or 0
    )
    cache_write = int(
        details.get("cache_creation_tokens")
        or details.get("cache_write_tokens")
        or details.get("cache_creation_input_tokens")
        or 0
    )
    return max(0, cache_read), max(0, cache_write)


def usage_from_remote_chat_response(data: dict[str, Any]) -> tuple[int, int, int, int]:
    """
    OpenAI / Anthropic / DeepSeek 兼容 usage（含 Chat Completions 与 Responses）。

    返回 (prompt, completion, cache_read, cache_write)。
    若上游给出 cache 拆分，prompt 记非缓存输入；优先 ``prompt_cache_miss_tokens``，
    否则 ``prompt/input_tokens - cache_read``（下限 0）。
    无 cache 字段时整段 prompt/input 记为 prompt，cache=0。

    DeepSeek Chat：``prompt_cache_hit_tokens``；Responses：``input_tokens_details.cached_tokens``。
    """
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return 0, 0, 0, 0

    prompt_raw = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

    cache_read = 0
    cache_write = 0
    # Chat Completions: prompt_tokens_details；Responses: input_tokens_details
    for key in ("prompt_tokens_details", "input_tokens_details"):
        read, write = _cache_from_token_details(usage.get(key))
        cache_read = max(cache_read, read)
        cache_write = max(cache_write, write)

    # Anthropic Messages：usage.cache_read_input_tokens / cache_creation_input_tokens
    cache_read = max(
        cache_read,
        int(usage.get("cache_read_input_tokens") or usage.get("cache_read_tokens") or 0),
    )
    cache_write = max(
        cache_write,
        int(usage.get("cache_creation_input_tokens") or usage.get("cache_write_tokens") or 0),
    )

    # DeepSeek / 部分 OpenAI 兼容 Chat：prompt_cache_hit_tokens（无独立 write）
    cache_read = max(cache_read, int(usage.get("prompt_cache_hit_tokens") or 0))

    if cache_read > 0 or cache_write > 0:
        if "prompt_cache_miss_tokens" in usage:
            prompt = max(0, int(usage.get("prompt_cache_miss_tokens") or 0))
        else:
            prompt = max(0, prompt_raw - cache_read)
    else:
        prompt = max(0, prompt_raw)

    return prompt, max(0, completion), max(0, cache_read), max(0, cache_write)
