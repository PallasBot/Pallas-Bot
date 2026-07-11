"""ACL-driven ban gate preprocessor.

策略：
- ACL 引擎评估 ``event.receive`` 行为，三种 target：
    - ``"*"`` 普通群/私聊消息
    - ``"group"`` group 自身封禁（group_id 维度评估）
    - ``"friend_request"`` / ``"group_invite"`` / 群内消息的 group 编码
- ACL 返回 ``allow=True`` → 放行。
- ACL fallback → 回退查 legacy 列（user_config.banned / group_config.banned /
  group_config.blocked_user_ids）。仅在此 fail-closed 短窗口兜底。
"""

from nonebot import logger
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import FriendRequestEvent, GroupRequestEvent
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor
from nonebot.utils import run_coro_with_shield

from pallas.core.perm.acl import AclDecision, AclSubject, evaluate_acl

from .ban_gate import query_group_ban_status_for_gate, query_user_ban_status_for_gate
from .helpers import event_actor_user_id, event_group_id


def _is_acl_decisive(decision: AclDecision) -> bool:
    """非 fallback 决策 = ACL 决策层直接给出结论，无需再查 legacy 列。"""
    return decision.source != "fallback"


def _event_action_target(event: Event, gid: int | None, uid: int | None) -> tuple[str, str]:
    """把 event 投影到 (action, target) 二元组。

    群维度评估 action='event.receive', target='group'。
    用户维度评估：好友邀请走 'friend_request'/'group_invite'；群消息走 'group:<gid>'；其他走 '*'。
    """
    if isinstance(event, FriendRequestEvent):
        return "event.receive", "friend_request"
    if isinstance(event, GroupRequestEvent) and getattr(event, "sub_type", "") == "invite":
        return "event.receive", "group_invite"
    return "event.receive", "*"


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

    # 1. group 维度 ACL（仅在有 gid 时评估；target="group" 是约定的群维度 token）
    if gid is not None:
        group_subject = AclSubject(group_id=gid, bot_id=bot_self_id)
        group_decision = await run_coro_with_shield(
            evaluate_acl(action="event.receive", target="group", subject=group_subject)
        )
        if not group_decision.allow:
            if _is_acl_decisive(group_decision):
                logger.debug("drop event in group gid={} acl source={}", gid, group_decision.source)
                raise IgnoredException("banned group by acl")
            group_banned = await run_coro_with_shield(query_group_ban_status_for_gate(gid))
            if group_banned:
                logger.debug("drop event in banned group gid={}", gid)
                raise IgnoredException("banned group")

    # 2. user 维度 ACL：用 group 编码 target 提高精度
    if uid is None:
        return
    action, generic_target = _event_action_target(event, gid, uid)
    user_action_target = (
        f"group:{gid}" if gid is not None and generic_target == "*" else generic_target
    )
    user_subject = AclSubject(user_id=uid, group_id=gid, bot_id=bot_self_id)
    user_decision = await run_coro_with_shield(
        evaluate_acl(action=action, target=user_action_target, subject=user_subject)
    )
    if _is_acl_decisive(user_decision):
        if user_decision.allow:
            return  # ACL 显式 allow，直接放行，不再做 legacy 探测
        # ACL 显式 deny，但需要区分 friend_request / group_invite 的 reject 处理
        await _reject_or_ignore(event, bot, uid, allow=False, banned=True)
        return

    # fallback: ACL 无规则 → 走 legacy 列
    global_banned = await run_coro_with_shield(query_user_ban_status_for_gate(uid))
    if not global_banned:
        return
    await _reject_or_ignore(event, bot, uid, allow=False, banned=True)


async def _reject_or_ignore(event: Event, bot: Bot, uid: int | None, *, allow: bool, banned: bool) -> None:
    """friend_request → reject + Ignored；group_invite → 同；其它 → Ignored。"""
    if allow:
        return
    if not banned:
        return
    if isinstance(event, FriendRequestEvent):
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
