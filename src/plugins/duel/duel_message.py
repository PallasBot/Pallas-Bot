from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message, MessageSegment

DuelContent = str | Message | MessageSegment


def duel_at(qq: str | int) -> MessageSegment:
    """QTE 等需要 @ 提醒时使用。"""
    return MessageSegment.at(int(qq))


def duel_display(qq: str | int) -> MessageSegment:
    """叙事、数值行等：展示开战时缓存的群昵称/名片。"""
    from src.plugins.duel.duel_labels import duel_label_for

    return duel_text(duel_label_for(qq))


def duel_text(text: str) -> MessageSegment:
    return MessageSegment.text(text)


def is_duel_message_segment(value: object) -> bool:
    if isinstance(value, MessageSegment):
        return True
    return not isinstance(value, (str, bytes, Message)) and hasattr(value, "type") and hasattr(value, "data")


def duel_plain(text: str) -> Message:
    if is_duel_message_segment(text):
        return Message(text)  # type: ignore[arg-type]
    if isinstance(text, Message):
        return text
    t = (text or "").strip()
    return Message(t) if t else Message()


def coerce_duel_message(value: DuelContent) -> Message:
    if isinstance(value, Message):
        return value
    if is_duel_message_segment(value):
        return Message(value)  # type: ignore[arg-type]
    if isinstance(value, str):
        return duel_plain(value)
    return duel_plain(str(value))


def message_has_content(msg: DuelContent) -> bool:
    if not isinstance(msg, Message):
        msg = coerce_duel_message(msg)
    for seg in msg:
        if seg.type in ("at", "image", "face", "record", "video"):
            return True
        if seg.type == "text" and str(seg.data.get("text", "")).strip():
            return True
    return False


def message_plain_fingerprint(msg: Message) -> str:
    return " ".join(msg.extract_plain_text().split()).strip()[:120]


def duel_join_blocks(blocks: list[Message], sep: str = "\n\n") -> Message:
    kept = [b for b in blocks if message_has_content(b)]
    if not kept:
        return Message()
    out = kept[0]
    for block in kept[1:]:
        if sep:
            out = out + MessageSegment.text(sep) + block
        else:
            out = out + block
    return out


def duel_join_lines(*lines: DuelContent, sep: str = "\n") -> Message:
    return duel_join_blocks([coerce_duel_message(line) for line in lines], sep=sep)


def duel_join_spaced(*parts: DuelContent) -> Message:
    kept = [coerce_duel_message(p) for p in parts if message_has_content(p)]
    if not kept:
        return Message()
    out = kept[0]
    for part in kept[1:]:
        out = out + MessageSegment.text(" ") + part
    return out


def append_duel_message(base: DuelContent, extra: DuelContent, sep: str = "\n") -> Message:
    base_msg = coerce_duel_message(base)
    extra_msg = coerce_duel_message(extra)
    if not message_has_content(base_msg):
        return extra_msg
    if not message_has_content(extra_msg):
        return base_msg
    return base_msg + MessageSegment.text(sep) + extra_msg


def apply_ab_placeholders(template: str, challenger_id: str, defender_id: str) -> Message:
    if not template:
        return Message()
    from src.plugins.duel.duel_labels import duel_label_for

    markers: list[tuple[str, str]] = [
        ("<A>", duel_label_for(challenger_id)),
        ("<B>", duel_label_for(defender_id)),
    ]
    segments: list[MessageSegment] = []
    rest = template
    while rest:
        best_idx = -1
        best_marker = ""
        best_name = ""
        for marker, name in markers:
            idx = rest.find(marker)
            if idx >= 0 and (best_idx < 0 or idx < best_idx):
                best_idx = idx
                best_marker = marker
                best_name = name
        if best_idx < 0:
            segments.append(MessageSegment.text(rest))
            break
        if best_idx > 0:
            segments.append(MessageSegment.text(rest[:best_idx]))
        segments.append(duel_text(best_name))
        rest = rest[best_idx + len(best_marker) :]
    return Message(segments)
