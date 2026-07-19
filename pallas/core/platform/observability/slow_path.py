from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

from nonebot import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value


@lru_cache(maxsize=32)
def slow_path_threshold_ms(env_key: str, default: float) -> float:
    raw = repo_env_raw_value(env_key)
    if raw is None:
        return float(default)
    try:
        value = float(str(raw).strip())
    except ValueError:
        return float(default)
    return max(0.0, value)


def clear_slow_path_threshold_cache() -> None:
    slow_path_threshold_ms.cache_clear()


def _format_field(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class SlowPathTimer:
    def __init__(self, scope: str, *, threshold_ms: float, log_level: str = "debug") -> None:
        self.scope = scope
        self.threshold_ms = max(0.0, float(threshold_ms))
        self.log_level = str(log_level or "debug").strip().lower() or "debug"
        self._started = time.perf_counter()
        self._last_mark = self._started
        self._stages: list[tuple[str, float]] = []

    def mark(self, name: str, *, now: float | None = None) -> float:
        current = time.perf_counter() if now is None else float(now)
        elapsed_ms = max(0.0, (current - self._last_mark) * 1000)
        self._stages.append((name, elapsed_ms))
        self._last_mark = current
        return elapsed_ms

    def finish(self, *, now: float | None = None, **fields: Any) -> float:
        current = time.perf_counter() if now is None else float(now)
        total_ms = max(0.0, (current - self._started) * 1000)
        if total_ms < self.threshold_ms:
            return total_ms
        stage_text = ",".join(f"{name}={elapsed_ms:.1f}ms" for name, elapsed_ms in self._stages) or "-"
        field_text = (
            " ".join(f"{key}={_format_field(value)}" for key, value in sorted(fields.items()) if value is not None)
            or "-"
        )
        log_method = getattr(logger, self.log_level, logger.warning)
        log_method(
            "{} slow_path elapsed_ms={:.1f} stages={} {}",
            self.scope,
            total_ms,
            stage_text,
            field_text,
        )
        return total_ms
