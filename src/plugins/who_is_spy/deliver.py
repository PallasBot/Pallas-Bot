"""向玩家投递词语/投票说明：好友私聊 → 群临时会话 → QQ 邮箱。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from nonebot import logger
from nonebot.adapters.onebot.v11.exception import ActionFailed, ApiNotAvailable, NetworkError

from src.plugins.bot_status.config import MailConfig, get_bot_status_config
from src.plugins.bot_status.utils import send_mail

from .config import get_spy_config

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

DeliveryChannel = Literal["private", "temp", "email", "failed"]
_SEND_ERRORS = (ActionFailed, ApiNotAvailable, NetworkError)

# NapCat 对未加好友的群临时会话常不稳定；按 bot 缓存探测结果。
_temp_session_ok: dict[int, bool | None] = {}


def qq_mail(user_id: int) -> str:
    return f"{int(user_id)}@qq.com"


def mail_config_for(recipient: str) -> MailConfig | None:
    cfg = get_spy_config()
    if not cfg.spy_email_fallback:
        return None
    status = get_bot_status_config()
    mail = MailConfig(
        user=status.bot_status_smtp_user,
        password=status.bot_status_smtp_password,
        server=status.bot_status_smtp_server,
        port=status.bot_status_smtp_port,
        notice_email=recipient,
    )
    if not mail.check_params():
        return None
    return mail


@dataclass(frozen=True)
class DeliveryOutcome:
    channel: DeliveryChannel
    ok: bool


async def send_private(bot: Bot, user_id: int, message: str, *, group_id: int | None = None) -> bool:
    payload: dict = {"user_id": int(user_id), "message": message}
    if group_id is not None:
        payload["group_id"] = int(group_id)
    try:
        await bot.call_api("send_private_msg", **payload)
        return True
    except _SEND_ERRORS as err:
        logger.debug(
            "who_is_spy: send_private failed bot={} user={} group={} err={}",
            bot.self_id,
            user_id,
            group_id,
            err,
        )
        return False


async def send_email(user_id: int, *, subject: str, body: str) -> bool:
    mail = mail_config_for(qq_mail(user_id))
    if mail is None:
        return False
    err = await send_mail(subject, body, mail)
    if err:
        logger.warning("who_is_spy: email to {} failed: {}", qq_mail(user_id), err)
        return False
    return True


async def deliver_player_message(
    bot: Bot,
    *,
    group_id: int,
    user_id: int,
    private_text: str,
    email_subject: str,
    email_body: str,
) -> DeliveryOutcome:
    bot_id = int(bot.self_id)

    if await send_private(bot, user_id, private_text):
        return DeliveryOutcome("private", True)

    temp_known = _temp_session_ok.get(bot_id)
    if temp_known is not False:
        if await send_private(bot, user_id, private_text, group_id=group_id):
            _temp_session_ok[bot_id] = True
            return DeliveryOutcome("temp", True)
        _temp_session_ok[bot_id] = False
        logger.info(
            "who_is_spy: bot {} temp session unavailable (NapCat/协议常不支持未加好友临时会话)，将尝试 QQ 邮箱",
            bot_id,
        )

    if await send_email(user_id, subject=email_subject, body=email_body):
        return DeliveryOutcome("email", True)

    return DeliveryOutcome("failed", False)
