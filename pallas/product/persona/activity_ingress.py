"""群活跃度对主动发言与接话 ingress 的倍率。"""

from __future__ import annotations

ActivityLevel = str

_QUIET_MAX_MSGS_PER_HOUR = 3.0
_ACTIVE_MIN_MSGS_PER_HOUR = 8.0

_SPEAK_BIAS_MUL: dict[ActivityLevel, float] = {
    "quiet": 0.85,
    "normal": 1.0,
    "active": 1.12,
}
_REPLY_BIAS_MUL: dict[ActivityLevel, float] = {
    "quiet": 0.9,
    "normal": 1.0,
    "active": 1.08,
}
_SPEAK_THRESHOLD_MUL: dict[ActivityLevel, float] = {
    "quiet": 1.35,
    "normal": 1.0,
    "active": 0.88,
}


def classify_activity_level(msgs_per_hour_active: float) -> ActivityLevel:
    rate = max(0.0, float(msgs_per_hour_active))
    if rate >= _ACTIVE_MIN_MSGS_PER_HOUR:
        return "active"
    if 0.0 < rate < _QUIET_MAX_MSGS_PER_HOUR:
        return "quiet"
    return "normal"


def activity_speak_bias_multiplier(level: ActivityLevel) -> float:
    return _SPEAK_BIAS_MUL.get(str(level or "normal"), 1.0)


def activity_reply_bias_multiplier(level: ActivityLevel) -> float:
    return _REPLY_BIAS_MUL.get(str(level or "normal"), 1.0)


def activity_speak_threshold_multiplier(level: ActivityLevel) -> float:
    return _SPEAK_THRESHOLD_MUL.get(str(level or "normal"), 1.0)
