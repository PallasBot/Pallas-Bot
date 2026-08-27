"""静默期间全局压制消息（但放行命令）。

- 触发：reply_gate 命中 shut_up 时对该群建静默。
- 压制：静默期内丢弃该群所有主动消息（含被 @ 的内容对话、复读/接话/表情唤起），只放行命令。
- 解除：说「说话/回话」即时解除（该条放行）；到期自动解除。
"""

from __future__ import annotations

from nonebot import logger
from nonebot.adapters.onebot.v11 import MessageEvent, PokeNotifyEvent
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor

from pallas.core.foundation.command_prefix import strip_leading_command_marks
from pallas.core.platform.ingress.plugin_command_plaintext import (
    is_group_plugin_command_plaintext,
    is_plugin_command_plaintext,
)
from pallas.product.llm.shut_up import is_speak_request_text
from pallas.product.llm.silence import (
    is_group_silenced,
    silence_remaining_sec,
    try_clear_silence,
)

_GATE_REGISTERED = False


def _event_group_id(event) -> int | None:
    gid = getattr(event, "group_id", None)
    return gid if isinstance(gid, int) and gid > 0 else None


def _is_onebot_v11(event) -> bool:
    return "onebot.v11" in type(event).__module__


def _is_command_plaintext(plain: str) -> bool:
    if not plain:
        return False
    if is_group_plugin_command_plaintext(plain) or is_plugin_command_plaintext(plain):
        return True
    return plain.startswith("/") and strip_leading_command_marks(plain) != plain


async def suppress_group_silence(bot, event) -> None:
    if not _is_onebot_v11(event):
        return

    gid = _event_group_id(event)
    if gid is None:
        return
    if isinstance(event, PokeNotifyEvent) and is_group_silenced(int(bot.self_id), gid):
        raise IgnoredException("silenced group (poke)")
    if not isinstance(event, MessageEvent):
        return

    bot_id = int(bot.self_id)
    uid = getattr(event, "user_id", None)
    if isinstance(uid, int) and uid == bot_id:
        return

    plain = (event.get_plaintext() or "").strip()

    # 解除信号：说「说话/回话」且不带否定 → 清除静默，该条放行
    if is_speak_request_text(plain) and try_clear_silence(bot_id, gid):
        logger.info("Bot [{}] silence cleared in group [{}] by speak request", bot_id, gid)
        return

    if not is_group_silenced(bot_id, gid):
        return

    # 静默期内只放行命令（含说话解除信号已在上方处理）
    if _is_command_plaintext(plain):
        return

    remaining = int(silence_remaining_sec(bot_id, gid))
    logger.debug("Bot [{}] suppressed message in silenced group [{}] (remaining [{}]s)", bot_id, gid, remaining)
    raise IgnoredException("silenced group")


def register_silence_gate_runtime() -> None:
    global _GATE_REGISTERED
    if _GATE_REGISTERED:
        return

    @event_preprocessor
    async def silence_gate_preprocessor(bot, event) -> None:
        await suppress_group_silence(bot, event)

    logger.debug("[Silence gate] global suppression preprocessor registered")
    _GATE_REGISTERED = True
