from nonebot.adapters.milky.event import GroupMessageEvent
from nonebot.permission import Permission


async def _group(event: GroupMessageEvent) -> bool:
    return True


async def _group_member(event: GroupMessageEvent) -> bool:
    return event.data.group_member.role == "member"  # type: ignore[attr-defined]


async def _group_admin(event: GroupMessageEvent) -> bool:
    return event.data.group_member.role == "admin"  # type: ignore[attr-defined]


async def _group_owner(event: GroupMessageEvent) -> bool:
    return event.data.group_member.role == "owner"  # type: ignore[attr-defined]


GROUP = Permission(_group)
"""匹配任意群聊消息类型事件"""
GROUP_MEMBER: Permission = Permission(_group_member)
"""匹配任意群员群聊消息类型事件"""
GROUP_ADMIN: Permission = Permission(_group_admin)
"""匹配群管理员及群主的群聊消息类型事件"""
GROUP_OWNER: Permission = Permission(_group_owner)
"""匹配群主的群聊消息类型事件"""
