"""自动记忆写入的每日预算与冷却计时（auto_episode / auto_ip / session_summary 共用）。"""

from __future__ import annotations

import time


class DailyBudget:
    """按自然日计数的预算闸门；budget<=0 表示不限制。"""

    def __init__(self) -> None:
        self._date = ""
        self._used = 0

    def ok(self, budget: int) -> bool:
        budget = max(0, int(budget))
        if budget <= 0:
            return True
        today = time.strftime("%Y-%m-%d")
        if today != self._date:
            self._date = today
            self._used = 0
        return self._used < budget

    def bump(self, budget: int) -> None:
        budget = max(0, int(budget))
        if budget > 0:
            self._used += 1

    def used(self) -> int:
        return self._used

    def reset(self) -> None:
        self._date = ""
        self._used = 0


class WriteCooldown:
    """按 key（bot, group[, user]）记录最近写入时间，用于冷却判断。"""

    def __init__(self) -> None:
        self._last_at: dict[tuple[int, ...], float] = {}

    def ok(self, key: tuple[int, ...], cooldown_sec: int) -> bool:
        if cooldown_sec <= 0:
            return True
        last = self._last_at.get(key, 0.0)
        return (time.monotonic() - last) >= float(cooldown_sec)

    def mark(self, key: tuple[int, ...]) -> None:
        self._last_at[key] = time.monotonic()

    def tracked(self) -> int:
        return len(self._last_at)

    def clear(self) -> None:
        self._last_at.clear()
