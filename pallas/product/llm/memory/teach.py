"""从 @对话 话术中解析「记住」类教导，及教学注入的相加热冷却。"""

from __future__ import annotations

import re
import time

from .policy import classify_memory_candidate, normalize_episode_note

_TEACH_PREFIXES = (
    "记住：",
    "记住:",
    "请你记住",
    "要记住",
    "帮我记住",
)

_CQ_CODE_RE = re.compile(r"\[CQ:[^\]]+\]", re.IGNORECASE)

# 教学注入信号：消息含任一词即视为一次教学企图（无论是否带冒号/最终写入成功）
_TEACH_GUIDANCE_MARKERS = (
    "记住",
    "请记住",
    "请你记住",
    "帮我记住",
    "要记住",
    "帮我记",
    "记一下",
    "以后叫",
    "今后叫",
    "以后说",
    "以后回复",
    "以后就叫我",
)

# B3 相加热冷却：同 (bot, group, user) 短窗内教学注入计数，越阈值启动冷却并翻倍
_INJECTION_WINDOW_SEC = 600
_INJECTION_THRESHOLD = 3
_COOLDOWN_BASE_SEC = 900
_COOLDOWN_MAX_SEC = 86400

_hits: dict[tuple[int, ...], list[float]] = {}
_cooldown_until: dict[tuple[int, ...], float] = {}


def strip_cq_codes(text: str) -> str:
    return _CQ_CODE_RE.sub("", text or "").strip()


def looks_like_teach_guidance(text: str) -> bool:
    """教学式消息判定：命中任一下教信号（含 B1 拦截的「记住XX」变体）。"""
    plain = strip_cq_codes(text or "").strip()
    if not plain:
        return False
    return any(marker in plain for marker in _TEACH_GUIDANCE_MARKERS)


def note_teach_guidance(
    key: tuple[int, ...],
    *,
    window_sec: int = _INJECTION_WINDOW_SEC,
    threshold: int = _INJECTION_THRESHOLD,
    base_cooldown_sec: int = _COOLDOWN_BASE_SEC,
    max_cooldown_sec: int = _COOLDOWN_MAX_SEC,
    now: float | None = None,
) -> bool:
    """记录一次教学注入；冷却中或本次注入使计数越阈值时返回 True（应忽略教学）。

    冷却时长 = base × 2^(命中次数 - 阈值)，每次越阈值翻倍，封顶 max；同键
    冷却中继续命中不重复翻倍（避免单次轰炸瞬间打满）。
    """
    ts = time.time() if now is None else float(now)
    if _cooldown_until.get(key, 0.0) > ts:
        return True
    hits = _hits.setdefault(key, [])
    cutoff = ts - max(1, int(window_sec))
    hits[:] = [h for h in hits if h > cutoff]
    hits.append(ts)
    hits.sort()
    if len(hits) >= max(1, int(threshold)):
        over = len(hits) - int(threshold)
        duration = int(base_cooldown_sec) * (2**over)
        duration = min(duration, int(max_cooldown_sec))
        _cooldown_until[key] = max(_cooldown_until.get(key, 0.0), ts + duration)
        return True
    return False


def teach_guidance_cooldown_remaining(key: tuple[int, ...], *, now: float | None = None) -> float:
    ts = time.time() if now is None else float(now)
    return max(0.0, _cooldown_until.get(key, 0.0) - ts)


def reset_teach_guidance_state() -> None:
    """清空教学注入计数与冷却（供测试/重载）。"""
    _hits.clear()
    _cooldown_until.clear()


def parse_memory_teach(user_text: str) -> str | None:
    plain = strip_cq_codes(user_text)
    if not plain:
        return None
    for prefix in _TEACH_PREFIXES:
        if plain.startswith(prefix):
            body = plain[len(prefix) :].strip()
            if body and classify_memory_candidate(plain) == "episode_note":
                return normalize_episode_note(body, max_len=500)
    return None
