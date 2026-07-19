"""relogin 分片转发：worker / hub 共用的 HTTP 载荷结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ReplyKind = Literal["text", "image_base64"]


@dataclass
class ReplyItem:
    kind: ReplyKind
    content: str


@dataclass
class ReloginHandleResult:
    replies: list[ReplyItem] = field(default_factory=list)
    session_active: bool = False
    reject_hint: str | None = None


def result_to_payload(result: ReloginHandleResult) -> dict[str, Any]:
    return {
        "replies": [{"kind": item.kind, "content": item.content} for item in result.replies],
        "session_active": result.session_active,
        "reject_hint": result.reject_hint,
    }


def result_from_payload(payload: dict[str, Any]) -> ReloginHandleResult:
    replies: list[ReplyItem] = []
    for item in payload.get("replies") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        content = item.get("content")
        if kind in ("text", "image_base64") and isinstance(content, str):
            replies.append(ReplyItem(kind=kind, content=content))
    return ReloginHandleResult(
        replies=replies,
        session_active=bool(payload.get("session_active")),
        reject_hint=payload.get("reject_hint") if isinstance(payload.get("reject_hint"), str) else None,
    )
