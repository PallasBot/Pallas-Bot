"""可选 LLM 情感 refinement：默认关闭，不参与接话热路径。"""

from __future__ import annotations

from threading import Lock
from typing import Any

from src.foundation.config.repo_settings import repo_env_raw_value

from .affect_baseline import AFFECT_REFINE_SOURCE_NONE, empty_affect_refine, merge_affect_refine_into_profile

_config_lock = Lock()
_cached_enabled: bool | None = None


def llm_affect_refine_enabled() -> bool:
    global _cached_enabled
    with _config_lock:
        if _cached_enabled is not None:
            return _cached_enabled
        raw = repo_env_raw_value("LLM_AFFECT_REFINE_ENABLED")
        if raw is None:
            _cached_enabled = False
        else:
            _cached_enabled = raw.strip().lower() in ("1", "true", "yes", "on")
        return _cached_enabled


def clear_affect_refine_config_cache() -> None:
    global _cached_enabled
    with _config_lock:
        _cached_enabled = None


async def refine_group_style_affect(profile: dict[str, Any], *, group_id: int) -> dict[str, Any]:
    """批次 refresh 时可选调用 AI 仓；未启用时原样返回并保留 affect_refine 占位。"""
    _ = group_id
    if not llm_affect_refine_enabled():
        return merge_affect_refine_into_profile(profile, empty_affect_refine())
    # 进阶：在此调用 AI 仓 JSON-only 情感分析接口，合并 delta 后 source=llm。
    return merge_affect_refine_into_profile(
        profile,
        {**empty_affect_refine(), "source": AFFECT_REFINE_SOURCE_NONE},
    )
