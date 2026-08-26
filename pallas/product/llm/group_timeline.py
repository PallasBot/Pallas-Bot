"""最近群消息的共享时间线上下文。"""

from __future__ import annotations

from dataclasses import dataclass

from pallas.core.foundation.db import Message, make_message_repository
from pallas.product.llm.sender_identity import speaker_label
from pallas.product.llm.vision_content import extract_vision_message_payload
from pallas.product.persona.prompt_guard import sanitize_prompt_block, sanitize_prompt_literal

_TIMELINE_MAX_IMAGES = 3
_TIMELINE_TRIGGERS = frozenset({"alias", "mention", "followup", "ambient", "vision"})


@dataclass(frozen=True, slots=True)
class GroupTimelineImage:
    speaker: str
    text: str
    url: str


@dataclass(frozen=True, slots=True)
class GroupTimelineContext:
    text: str = ""
    images: tuple[GroupTimelineImage, ...] = ()


def should_include_group_timeline(*, is_to_me: bool, speak_trigger: str) -> bool:
    return bool(is_to_me or speak_trigger in _TIMELINE_TRIGGERS)


def format_group_timeline_context(
    messages: list[Message],
    *,
    self_bot_id: int | None = None,
) -> GroupTimelineContext:
    """将群消息压缩为文字时间线，并提取最近图片的结构化上下文。"""
    lines = ["【刚才的群聊】"]
    speaker_by_id: dict[int, str] = {}
    rendered: list[tuple[Message, str, str, bool]] = []
    image_items: list[GroupTimelineImage] = []
    seen_urls: set[str] = set()
    for message in messages:
        raw_message = str(getattr(message, "raw_message", "") or "")
        payload = extract_vision_message_payload(raw_message) if raw_message else None
        has_image = bool(payload and payload.has_image)
        source_text = payload.plain_text if has_image and payload is not None else str(message.plain_text or "")
        text = sanitize_prompt_literal(source_text, max_len=240)
        if not text and not has_image:
            continue
        speaker = speaker_label(
            message.user_id,
            message.sender_name,
            self_bot_id=self_bot_id or 0,
        )
        message_id = int(message.message_id) if message.message_id is not None else 0
        if message_id > 0:
            speaker_by_id[message_id] = speaker
        rendered.append((message, speaker, text, has_image))
        if has_image and payload is not None:
            for url in payload.image_urls:
                key = url.casefold()
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                image_items.append(GroupTimelineImage(speaker=speaker, text=text, url=url))
    for message, speaker, text, has_image in rendered:
        tail = ""
        reply_to = int(message.reply_to_message_id) if message.reply_to_message_id is not None else 0
        if reply_to > 0 and reply_to in speaker_by_id:
            tail = f"（回{speaker_by_id[reply_to]}的话）"
        display_text = f"[图片] {text}" if has_image and text else "[图片]" if has_image else text
        lines.append(f"- {speaker}{tail}：{display_text}")
    if len(lines) == 1:
        return GroupTimelineContext()
    return GroupTimelineContext(
        text=sanitize_prompt_block("\n".join(lines), max_len=2400),
        images=tuple(image_items[-_TIMELINE_MAX_IMAGES:]),
    )


def format_group_timeline(messages: list[Message], *, self_bot_id: int | None = None) -> str:
    """将已按时间排序的群消息压缩为带身份的 prompt 块。

    去编号：不带 message_id / 引用 id，引用关系口语化成「（回X的话）」，
    让模型读起来像一段连续群聊，而不是日志摘录。
    bot 发言标注为本 bot / 其他 bot，不混进群友。
    """
    return format_group_timeline_context(messages, self_bot_id=self_bot_id).text


async def build_recent_group_timeline_context(
    group_id: int,
    *,
    current_message_id: int | None,
    limit: int = 8,
    self_bot_id: int | None = None,
) -> GroupTimelineContext:
    """读取当前消息之前最近的同群消息及其中的图片上下文。"""
    cap = max(1, min(int(limit), 16))
    messages = await make_message_repository().find_recent_in_group(int(group_id), limit=cap + 1)
    visible = [message for message in messages if message.message_id != current_message_id]
    return format_group_timeline_context(visible[-cap:], self_bot_id=self_bot_id)


async def build_recent_group_timeline(
    group_id: int,
    *,
    current_message_id: int | None,
    limit: int = 8,
    self_bot_id: int | None = None,
) -> str:
    """读取当前消息之前最近的同群消息，不把当前消息重复注入。"""
    context = await build_recent_group_timeline_context(
        group_id,
        current_message_id=current_message_id,
        limit=limit,
        self_bot_id=self_bot_id,
    )
    return context.text
