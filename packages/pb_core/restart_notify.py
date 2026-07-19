"""牛牛重启：落盘待通知记录，上线后私聊触发者。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot import logger

from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

_PENDING_FILENAME = "restart_notify_pending.json"
_PENDING_TTL_SEC = 600.0


@dataclass(frozen=True)
class RestartNotifyPending:
    user_id: int
    bot_id: int
    mode: str
    requested_at: float


def restart_notify_path():
    return plugin_data_dir("pb_core", create=True) / _PENDING_FILENAME


def record_restart_notify(*, user_id: int, bot_id: int, mode: str) -> None:
    payload = {
        "user_id": int(user_id),
        "bot_id": int(bot_id),
        "mode": str(mode or "").strip(),
        "requested_at": time.time(),
    }
    path = restart_notify_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def clear_restart_notify_pending() -> None:
    path = restart_notify_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        path.with_suffix(".tmp").unlink(missing_ok=True)
    except OSError:
        pass


def load_restart_notify_pending() -> RestartNotifyPending | None:
    path = restart_notify_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        clear_restart_notify_pending()
        return None
    if not isinstance(raw, dict):
        clear_restart_notify_pending()
        return None
    try:
        user_id = int(raw["user_id"])
        bot_id = int(raw["bot_id"])
        requested_at = float(raw["requested_at"])
    except (KeyError, TypeError, ValueError):
        clear_restart_notify_pending()
        return None
    if time.time() - requested_at > _PENDING_TTL_SEC:
        clear_restart_notify_pending()
        return None
    mode = str(raw.get("mode") or "").strip()
    return RestartNotifyPending(
        user_id=user_id,
        bot_id=bot_id,
        mode=mode,
        requested_at=requested_at,
    )


def format_restart_online_message(*, bot_id: int, mode: str) -> str:
    text = f"牛牛 {bot_id} 已重新上线"
    if mode:
        text += f"（{mode}）"
    return f"{text}，重启完成。"


async def maybe_notify_restart_online(bot: Bot) -> None:
    pending = load_restart_notify_pending()
    if pending is None:
        return
    bot_id = int(bot.self_id)
    if bot_id != pending.bot_id:
        return
    message = format_restart_online_message(bot_id=bot_id, mode=pending.mode)
    try:
        await bot.send_private_msg(user_id=pending.user_id, message=message)
    except Exception as err:
        logger.warning(
            "pb_core restart notify failed bot={} user={}: {}",
            bot_id,
            pending.user_id,
            err,
        )
        return
    clear_restart_notify_pending()
    logger.info("pb_core restart notify sent bot={} user={}", bot_id, pending.user_id)
