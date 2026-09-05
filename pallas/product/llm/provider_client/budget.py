"""Provider 每日预算闸与 token 用量上报。"""

from __future__ import annotations

from typing import Any


def provider_daily_budget_ok(provider_id: str) -> bool:
    """提供方每日 token / 花费封顶闸（软上限，0=不限制）。

    任一达到上限即拒绝该提供方的新请求（返回 429），次日按天重置。
    """
    from pallas.product.llm.daily_budget import used_today
    from pallas.product.llm.providers_store import find_provider

    try:
        row = find_provider(provider_id)
    except Exception:
        row = None
    if not row:
        return True
    tokens_cap = int(row.get("daily_tokens_cap") or 0)
    cost_cap = float(row.get("daily_cost_cap") or 0.0)
    if tokens_cap <= 0 and cost_cap <= 0:
        return True
    used = used_today("provider", key=str(provider_id or "").strip().lower())
    if tokens_cap > 0 and used["tokens"] >= tokens_cap:
        return False
    if cost_cap > 0 and used["cost"] >= cost_cap:
        return False
    return True


def _record_usage_from_payload(
    data: dict[str, Any],
    *,
    task: str,
    provider_id: str,
    model: str,
    local: bool = False,
    telemetry_context: dict[str, str] | None = None,
) -> None:
    try:
        from pallas.product.llm.token_metrics import record_llm_token_usage
        from pallas.product.llm.token_usage import (
            usage_from_local_chat_response,
            usage_from_remote_chat_response,
        )

        if local:
            prompt, completion, cache_read, cache_write = usage_from_local_chat_response(data)
            if prompt == 0 and completion == 0:
                prompt, completion, cache_read, cache_write = usage_from_remote_chat_response(data)
        else:
            prompt, completion, cache_read, cache_write = usage_from_remote_chat_response(data)
            if prompt == 0 and completion == 0 and cache_read == 0 and cache_write == 0:
                prompt, completion, cache_read, cache_write = usage_from_local_chat_response(data)
        record_llm_token_usage(
            task=task,
            provider=provider_id or None,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            trigger_source=str((telemetry_context or {}).get("trigger_source") or "") or None,
        )
    except Exception:
        pass
