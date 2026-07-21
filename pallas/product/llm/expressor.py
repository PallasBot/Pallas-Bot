"""口语改写指令：把生成句收成群聊口气。"""

from __future__ import annotations


def build_expressor_instruction() -> str:
    return (
        "请把待改写内容收成一句日常群聊口语：可重组语序，但必须保留原意；"
        "勿扩写、勿加设定词、勿加「继续聊/换个话题」类尾缀；不要解释。只输出一句，长度接近原文。"
    )


def build_expressor_user_text(
    *,
    user_text: str,
    raw_reply: str,
    reason: str = "",
    style_suffix: str = "",
) -> str:
    message = str(user_text or "").strip()
    candidate = str(raw_reply or "").strip()
    if not message or not candidate or "[CQ:" in message or "[CQ:" in candidate:
        return ""
    reason_text = str(reason or "").strip()
    suffix = str(style_suffix or "").strip()
    parts = [
        f"【用户消息】{message}",
        f"【待改写】{candidate}",
    ]
    if reason_text:
        parts.append(f"【改写原因】{reason_text}")
    if suffix:
        parts.append(suffix)
    parts.append(build_expressor_instruction())
    return "\n".join(parts)
