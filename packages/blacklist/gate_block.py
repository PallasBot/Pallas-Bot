"""ACL-driven ban gate preprocessor.

策略：
- ACL 引擎评估 ``event.receive``：
    - 群自身封禁：``target=ACL_TARGET_GROUP_BAN``（``"group"``）
    - 群内黑名单用户：``target=group:{gid}``
    - 好友/群邀请：``friend_request`` / ``group_invite``
    - 其它：``"*"``
- ACL 返回 decisive 决策 → 直接放行或拦截。
- ACL fallback（无规则）→ 回退 legacy 列（含 group_blocked），与迁移窗口一致。
"""

from nonebot import logger
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import FriendRequestEvent, GroupRequestEvent
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor
from nonebot.utils import run_coro_with_shield

from pallas.core.perm.acl import (
    ACL_TARGET_ANY,
    ACL_TARGET_GROUP_BAN,
    AclDecision,
    AclSubject,
    evaluate_acl,
    group_block_target,
)

from .ban_gate import (
    query_group_ban_status_for_gate,
    query_group_blocked_for_gate,
    query_user_ban_status_for_gate,
)
from .helpers import event_actor_user_id, event_group_id


def _is_acl_decisive(decision: AclDecision) -> bool:
    """非 fallback 决策 = ACL 决策层直接给出结论，无需再查 legacy 列。"""
    return decision.source != "fallback"


def _event_user_target(event: Event, gid: int | None) -> str:
    """用户维度评估的 target。"""
    if isinstance(event, FriendRequestEvent):
        return "friend_request"
    if isinstance(event, GroupRequestEvent) and getattr(event, "sub_type", "") == "invite":
        return "group_invite"
    if gid is not None:
        return group_block_target(gid)
    return ACL_TARGET_ANY


@event_preprocessor
async def block_globally_banned_users(bot: Bot, event: Event):
    if "onebot.v11" not in type(event).__module__:
        return

    gid = event_group_id(event)
    uid = event_actor_user_id(event)
    if uid is not None and uid == int(bot.self_id):
        return

    try:
        bot_self_id: int | None = int(bot.self_id)
    except Exception:
        bot_self_id = None

    # 1. 群自身封禁（target 与 ban_gate / migration 写入一致）
    if gid is not None:
        group_subject = AclSubject(group_id=gid, bot_id=bot_self_id)
        group_decision = await run_coro_with_shield(
            evaluate_acl(
                action="event.receive",
                target=ACL_TARGET_GROUP_BAN,
                subject=group_subject,
            )
        )
        if _is_acl_decisive(group_decision):
            if not group_decision.allow:
                logger.debug("drop event in group gid={} acl source={}", gid, group_decision.source)
                raise IgnoredException("banned group by acl")
        else:
            group_banned = await run_coro_with_shield(query_group_ban_status_for_gate(gid))
            if group_banned:
                logger.debug("drop event in banned group gid={}", gid)
                raise IgnoredException("banned group")

    # 2. 用户维度（全局封禁 / 群内黑名单）
    if uid is None:
        return
    user_target = _event_user_target(event, gid)
    user_subject = AclSubject(user_id=uid, group_id=gid, bot_id=bot_self_id)
    user_decision = await run_coro_with_shield(
        evaluate_acl(action="event.receive", target=user_target, subject=user_subject)
    )
    if _is_acl_decisive(user_decision):
        if user_decision.allow:
            return
        await _reject_or_ignore(event, bot, uid, global_banned=True)
        return

    # fallback: ACL 无规则 → legacy（必须仍查 group_blocked，避免迁移窗口漏拦）
    global_banned = await run_coro_with_shield(query_user_ban_status_for_gate(uid))
    group_blocked = False
    if gid is not None:
        group_blocked = await run_coro_with_shield(query_group_blocked_for_gate(gid, uid))
    if not global_banned and not group_blocked:
        return
    # 好友请求仅在全局封禁时拒绝（与改前一致）
    if isinstance(event, FriendRequestEvent) and not global_banned:
        return
    await _reject_or_ignore(event, bot, uid, global_banned=global_banned)


async def _reject_or_ignore(
    event: Event,
    bot: Bot,
    uid: int | None,
    *,
    global_banned: bool,
) -> None:
    """friend_request / group_invite → reject + Ignored；其它 → Ignored。"""
    if isinstance(event, FriendRequestEvent):
        if not global_banned:
            return
        try:
            await event.reject(bot)
        except Exception as e:
            logger.warning("reject friend request from banned user uid={} failed: {}", uid, e)
        raise IgnoredException("banned user")
    if isinstance(event, GroupRequestEvent) and getattr(event, "sub_type", "") == "invite":
        try:
            await event.reject(bot)
        except Exception as e:
            logger.warning("reject group invite from banned user uid={} failed: {}", uid, e)
        raise IgnoredException("banned user")
    raise IgnoredException("banned user")
