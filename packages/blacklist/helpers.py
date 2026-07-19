import re

from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import (
    FriendRequestEvent,
    GroupMessageEvent,
    GroupRecallNoticeEvent,
    GroupRequestEvent,
    GroupUploadNoticeEvent,
    MessageEvent,
    PokeNotifyEvent,
    PrivateMessageEvent,
)

from pallas.core.foundation.config import GroupConfig
from pallas.core.perm import satisfies_command_permission


def collect_target_qqs_from_plain_and_message(plain_text: str, message) -> list[int]:
    ids: list[int] = []
    for seg in message:
        if seg.type != "at":
            continue
        qq = seg.data.get("qq")
        if qq in (None, "all", "0"):
            continue
        try:
            ids.append(int(qq))
        except (TypeError, ValueError):
            continue
    ids.extend(int(m.group(1)) for m in re.finditer(r"(?<![0-9])([1-9][0-9]{4,14})(?![0-9])", plain_text or ""))
    out: list[int] = []
    seen: set[int] = set()
    for uid in ids:
        if uid not in seen:
            seen.add(uid)
            out.append(uid)
    return out


def collect_group_ids_from_plain(plain_text: str) -> list[int]:
    ids = [int(m.group(1)) for m in re.finditer(r"(?<![0-9])([1-9][0-9]{4,14})(?![0-9])", plain_text or "")]
    out: list[int] = []
    seen: set[int] = set()
    for gid in ids:
        if gid not in seen:
            seen.add(gid)
            out.append(gid)
    return out


_LIST_DISPLAY_LIMIT = 50


async def query_global_banned_user_ids() -> list[int]:
    from pallas.core.foundation.db import get_db_backend

    backend = get_db_backend()
    if backend == "mongodb":
        from pallas.core.foundation.db.modules import UserConfigModule

        docs = await UserConfigModule.find(UserConfigModule.banned == True).to_list()  # noqa: E712
        return sorted(int(d.user_id) for d in docs)
    if backend == "postgresql":
        from sqlalchemy import select

        from pallas.core.foundation.db.repository_pg import UserConfigRow, get_session

        async with get_session(read_only=True) as session:
            result = await session.execute(select(UserConfigRow.user_id).where(UserConfigRow.banned.is_(True)))
            return sorted(int(row[0]) for row in result.all())
    return []


async def query_global_banned_group_ids() -> list[int]:
    from pallas.core.foundation.db import get_db_backend

    backend = get_db_backend()
    if backend == "mongodb":
        from pallas.core.foundation.db.modules import GroupConfigModule

        docs = await GroupConfigModule.find(GroupConfigModule.banned == True).to_list()  # noqa: E712
        return sorted(int(d.group_id) for d in docs)
    if backend == "postgresql":
        from sqlalchemy import select

        from pallas.core.foundation.db.repository_pg import GroupConfigRow, get_session

        async with get_session(read_only=True) as session:
            result = await session.execute(select(GroupConfigRow.group_id).where(GroupConfigRow.banned.is_(True)))
            return sorted(int(row[0]) for row in result.all())
    return []


def format_id_list(ids: list[int], *, empty_hint: str) -> str:
    if not ids:
        return empty_hint
    shown = ids[:_LIST_DISPLAY_LIMIT]
    text = ", ".join(map(str, shown))
    if len(ids) > _LIST_DISPLAY_LIMIT:
        text += f" … 共 {len(ids)} 个"
    return text


async def build_blacklist_view_message(group_id: int | None) -> str:
    if group_id is None:
        users = await query_global_banned_user_ids()
        groups = await query_global_banned_group_ids()
        return "\n".join([
            "博士，米诺斯在册名单如下：",
            f"全局用户拉黑：{format_id_list(users, empty_hint='（无）')}",
            f"全局群拉黑：{format_id_list(groups, empty_hint='（无）')}",
        ])
    blocked = await GroupConfig(group_id).blocked_user_ids()
    group_banned = await GroupConfig(group_id).is_banned()
    lines = [
        f"博士，群 {group_id} 的名单如下：",
        f"本群屏蔽用户：{format_id_list(blocked, empty_hint='（无）')}",
    ]
    if group_banned:
        lines.append("本群状态：已被全局群拉黑")
    else:
        lines.append("本群状态：未被全局群拉黑")
    return "\n".join(lines)


def event_group_id(event: Event) -> int | None:
    gid = getattr(event, "group_id", None)
    if isinstance(gid, int) and gid > 0:
        return gid
    return None


def event_actor_user_id(event: Event) -> int | None:
    if isinstance(event, MessageEvent):
        uid = getattr(event, "user_id", None)
        return uid if isinstance(uid, int) else None
    if isinstance(event, (PokeNotifyEvent, GroupUploadNoticeEvent, FriendRequestEvent)):
        return event.user_id
    if isinstance(event, GroupRequestEvent):
        return event.user_id
    if isinstance(event, GroupRecallNoticeEvent):
        return event.operator_id
    op = getattr(event, "operator_id", None)
    if isinstance(op, int):
        return op
    uid = getattr(event, "user_id", None)
    return uid if isinstance(uid, int) else None


async def can_manage_blacklist(bot: Bot, event: Event) -> bool:
    if not isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
        return False
    return await satisfies_command_permission(bot, event, "blacklist.add")
