"""AI 回调结果投递到 QQ 群。"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from nonebot import logger
from nonebot.adapters.onebot.v11.exception import NetworkError
from nonebot.exception import ActionFailed

if TYPE_CHECKING:
    from fastapi import UploadFile

_CALLBACK_SEND_ERRORS = (ActionFailed, NetworkError)


async def send_group_message(bot, group_id: int, message: str) -> bool:
    try:
        await bot.call_api(
            "send_group_msg",
            **{
                "message": message,
                "group_id": group_id,
            },
        )
        return True
    except _CALLBACK_SEND_ERRORS as e:
        logger.warning("AI callback send_group_msg failed group={}: {}", group_id, e)
        return False


async def send_group_voice(bot, group_id: int, file: UploadFile) -> bool:
    file_content = await file.read()
    base64_file = base64.b64encode(file_content).decode()
    try:
        await bot.call_api(
            "send_group_msg",
            **{
                "message": f"[CQ:record,file=base64://{base64_file}]",
                "group_id": group_id,
            },
        )
        return True
    except _CALLBACK_SEND_ERRORS as e:
        logger.warning("AI callback send voice failed group={}: {}", group_id, e)
        return False
