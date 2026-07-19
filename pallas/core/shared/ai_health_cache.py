"""AI /health 探活结果缓存，供 probe 与插件读取统一运行态。"""

from __future__ import annotations

from typing import Any

_last_ai_health_body: dict[str, Any] | None = None


def update_ai_health_cache(body: object) -> None:
    global _last_ai_health_body
    if isinstance(body, dict):
        _last_ai_health_body = body
        return
    _last_ai_health_body = None


def cached_ai_health_body() -> dict[str, Any] | None:
    return _last_ai_health_body


def clear_ai_health_cache() -> None:
    global _last_ai_health_body
    _last_ai_health_body = None
