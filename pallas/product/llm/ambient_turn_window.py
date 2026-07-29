"""闲聊 ambient 攒窗：短时间内的连发只评估首条，压低被动开口率。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pallas.core.foundation.config.repo_settings import repo_env_raw_value

_DEFAULT_IDLE_SEC = 1.5


@dataclass
class _GroupAmbientBuf:
    texts: list[str] = field(default_factory=list)
    last_mono: float = 0.0


_BUFFERS: dict[tuple[int, int], _GroupAmbientBuf] = {}


def ambient_turn_window_enabled() -> bool:
    raw = repo_env_raw_value("PALLAS_LLM_AMBIENT_TURN_WINDOW")
    if raw is None:
        return True
    text = str(raw).strip().lower()
    if text in ("0", "false", "no", "off"):
        return False
    return True


def ambient_turn_idle_sec() -> float:
    raw = repo_env_raw_value("PALLAS_LLM_AMBIENT_TURN_IDLE_SEC")
    if raw is None:
        return _DEFAULT_IDLE_SEC
    try:
        return max(0.2, float(str(raw).strip()))
    except ValueError:
        return _DEFAULT_IDLE_SEC


def clear_ambient_turn_buffers_for_tests() -> None:
    _BUFFERS.clear()


def note_ambient_turn_and_should_flush(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    text: str,
    force: bool = False,
) -> tuple[bool, str]:
    """ambient 是否应进入 speak 评估。

    ``force=True``（@ / mention / followup）立即放行。
    同一群在 ``idle`` 秒内的后续 ambient 只记账、不触发，避免热群连发刷 LLM。
    """
    del user_id  # 预留按用户分窗
    body = (text or "").strip()
    if force or group_id is None or not ambient_turn_window_enabled():
        return True, body

    key = (int(bot_id), int(group_id))
    now = time.monotonic()
    idle = ambient_turn_idle_sec()
    buf = _BUFFERS.get(key)
    if buf is None:
        buf = _GroupAmbientBuf()
        _BUFFERS[key] = buf

    if not buf.texts or (now - buf.last_mono) >= idle:
        buf.texts = [body] if body else []
        buf.last_mono = now
        return True, body

    if body:
        buf.texts.append(body)
        if len(buf.texts) > 8:
            buf.texts = buf.texts[-8:]
    buf.last_mono = now
    return False, ""
