from __future__ import annotations

import re
from typing import TypedDict


class ApprovalNoticeMeta(TypedDict):
    kind: str
    target_id: str


_FRIEND_NOTICE_RE = re.compile(r"^\[好友申请\]\s*申请人：[^\n]*（(\d+)）", re.MULTILINE)
_GROUP_NOTICE_RE = re.compile(r"^\[入群邀请\]\s*邀请人：[^\n]*\n群：[^\n]*（(\d+)）", re.MULTILINE)


def parse_approval_notice_meta(text: str | None) -> ApprovalNoticeMeta | None:
    if not text:
        return None
    friend_match = _FRIEND_NOTICE_RE.search(text)
    if friend_match:
        return {"kind": "friend", "target_id": friend_match.group(1)}
    group_match = _GROUP_NOTICE_RE.search(text)
    if group_match:
        return {"kind": "group", "target_id": group_match.group(1)}
    return None
