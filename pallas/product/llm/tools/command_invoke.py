"""将 LLM tool 参数渲染为插件命令并派发到群消息处理链。"""

from __future__ import annotations

import time
from string import Formatter
from typing import TYPE_CHECKING, Any

import nonebot.message as nb_message
from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment

from pallas.core.perm import satisfies_command_permission

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext


class CommandTemplateError(ValueError):
    pass


def render_command_template(template: str, arguments: dict[str, Any]) -> str:
    """用 tool 参数填充命令模板，缺失键抛错。"""
    fields = {field_name for _, field_name, _, _ in Formatter().parse(template) if field_name}
    missing = [name for name in fields if name not in arguments]
    if missing:
        msg = f"missing template fields: {', '.join(missing)}"
        raise CommandTemplateError(msg)
    try:
        return template.format(**{key: str(arguments[key]) for key in fields})
    except (KeyError, ValueError) as exc:
        raise CommandTemplateError(str(exc)) from exc


def serialize_event_source_segments(
    event: Any,
    *,
    bot_id: int | str | None = None,
) -> list[dict[str, Any]]:
    """从原消息提取可复用的图片/@/显式「自己」段。"""
    message = getattr(event, "original_message", None)
    if message is None:
        get_message = getattr(event, "get_message", None)
        if callable(get_message):
            message = get_message()
        else:
            message = getattr(event, "message", None)
    if message is None:
        return []

    resolved_bot_id = bot_id
    if resolved_bot_id is None:
        resolved_bot_id = getattr(event, "self_id", None)
    bot_key = str(resolved_bot_id) if resolved_bot_id is not None else ""

    out: list[dict[str, Any]] = []
    seen_at: set[str] = set()
    for segment in message:
        seg_type = getattr(segment, "type", None)
        data = getattr(segment, "data", None) or {}
        if not isinstance(data, dict):
            continue
        if seg_type == "at":
            qq = data.get("qq")
            if qq is None or str(qq) in ("all", "0"):
                continue
            key = str(qq)
            if bot_key and key == bot_key:
                continue
            if key in seen_at:
                continue
            seen_at.add(key)
            out.append({"type": "at", "qq": key})
            continue
        if seg_type == "image":
            item: dict[str, Any] = {"type": "image"}
            url = data.get("url")
            file_value = data.get("file")
            if isinstance(url, str) and url.strip():
                item["url"] = url.strip()
            if isinstance(file_value, str) and file_value.strip():
                file_text = file_value.strip()
                item["file"] = file_text
                if "url" not in item and file_text.startswith(("http://", "https://")):
                    item["url"] = file_text
            if "url" in item or "file" in item:
                out.append(item)
            continue
        if seg_type == "text" and str(data.get("text") or "").strip() == "自己":
            out.append({"type": "text", "text": "自己"})
    return out


def source_segments_for_command(
    segments: tuple[dict[str, Any], ...],
    *,
    mode: str,
) -> tuple[dict[str, Any], ...]:
    """仅素材型命令携带原消息素材；无素材时才补「自己」给生成类插件。"""
    if mode != "media":
        return ()
    if segments:
        return segments
    return ({"type": "text", "text": "自己"},)


def append_source_segments_to_message(
    message: Message,
    segments: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> Message:
    if not segments:
        return message
    for item in segments:
        if not isinstance(item, dict):
            continue
        seg_type = str(item.get("type") or "").strip()
        if seg_type == "at":
            qq = item.get("qq")
            if qq is None or str(qq) in ("all", "0"):
                continue
            message = message + MessageSegment.at(qq)
            continue
        if seg_type == "image":
            url = item.get("url")
            file_value = item.get("file")
            if isinstance(url, str) and url:
                message = message + MessageSegment.image(url)
            elif isinstance(file_value, str) and file_value:
                message = message + MessageSegment.image(file_value)
            continue
        if seg_type == "text" and str(item.get("text") or "").strip() == "自己":
            message = message + MessageSegment.text("自己")
    return message


def build_synthetic_group_event(
    *,
    bot_id: int,
    group_id: int,
    user_id: int,
    text: str,
    source_segments: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> GroupMessageEvent:
    plain = (text or "").strip()
    message = append_source_segments_to_message(Message(plain), source_segments)
    return GroupMessageEvent(
        time=int(time.time()),
        self_id=bot_id,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=-int(time.time() * 1000) % 2_000_000_000,
        user_id=user_id,
        message=message,
        raw_message=plain,
        font=0,
        sender={"user_id": user_id, "nickname": "llm", "card": "", "role": "member"},
        group_id=group_id,
    )


async def dispatch_group_command_text(
    ctx: ToolInvokeContext,
    *,
    command_id: str,
    command_text: str,
    source_segments_mode: str = "none",
) -> dict[str, Any]:
    if ctx.group_id is None:
        return {"ok": False, "error": "group_context_required"}
    plain = (command_text or "").strip()
    if not plain:
        return {"ok": False, "error": "empty_command_text"}

    try:
        bot = get_bot(str(ctx.bot_id))
    except Exception as err:
        logger.warning("llm command dispatch get_bot failed bot_id={}: {}", ctx.bot_id, err)
        return {"ok": False, "error": "bot_unavailable"}

    source_segments = source_segments_for_command(
        ctx.source_segments,
        mode=source_segments_mode,
    )
    event = build_synthetic_group_event(
        bot_id=ctx.bot_id,
        group_id=ctx.group_id,
        user_id=ctx.user_id,
        text=plain,
        source_segments=source_segments,
    )
    if not await satisfies_command_permission(bot, event, command_id):
        return {"ok": False, "error": "permission_denied", "command_id": command_id}

    await nb_message.handle_event(bot, event)
    return {
        "ok": True,
        "dispatched": True,
        "command_id": command_id,
        "command_text": plain,
        "source_segment_count": len(source_segments),
    }
