from nonebot import logger
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import FriendRequestEvent, GroupRequestEvent
from nonebot.exception import IgnoredException
from nonebot.message import event_preprocessor
from nonebot.utils import run_coro_with_shield

from pallas.core.perm.acl import AclDecision, AclSubject, evaluate_acl

from .ban_gate import query_group_ban_status_for_gate, query_group_blocked_for_gate, query_user_ban_status_for_gate
from .helpers import event_actor_user_id, event_group_id


def _decision_to_ban_bool(decision: AclDecision) -> bool:
    return not decision.allow


@event_preprocessor
async def block_globally_banned_users(bot: Bot, event: Event):
    if "onebot.v11" not in type(event).__module__:
        return

    gid = event_group_id(event)
    uid = event_actor_user_id(event)
    if uid is not None and uid == int(bot.self_id):
        uid = None

    bot_self_id: int | None
    try:
        bot_self_id = int(bot.self_id)
    except Exception:
        bot_self_id = None

    subject = AclSubject(user_id=uid, group_id=gid, bot_id=bot_self_id)

    if gid is not None:
        try:
            event_action = "event.receive"
            group_decision: AclDecision = await run_coro_with_shield(
                evaluate_acl(action=event_action, target="*", subject=AclSubject(group_id=gid, bot_id=bot_self_id))
            )
            if not group_decision.allow:
                if group_decision.source == "fallback":
                    group_banned = await run_coro_with_shield(query_group_ban_status_for_gate(gid))
                    if group_banned:
                        logger.debug(f"drop event in banned group [{gid}]")
                        raise IgnoredException("banned group")
                else:
                    logger.debug(f"drop event by ACL group rule gid=[{gid}] source={group_decision.source}")
                    raise IgnoredException("banned group by acl")
        except IgnoredException:
            raise
        except Exception:
            pass

    if uid is None:
        return

    user_action = "event.receive"
    target_kind = (
        "friend_request" if isinstance(event, FriendRequestEvent)
        else "group_invite" if isinstance(event, GroupRequestEvent) and event.sub_type == "invite"
        else "*"
    )
    user_decision: AclDecision = await run_coro_with_shield(
        evaluate_acl(action=user_action, target=target_kind, subject=subject)
    )
    group_blocked = False
    if gid is not None:
        if user_decision.source == "fallback":
            group_blocked = await run_coro_with_shield(query_group_blocked_for_gate(gid, uid))
            if group_blocked:
                global_banned = await run_coro_with_shield(query_user_ban_status_for_gate(uid))
            else:
                global_banned = False
        else:
            global_banned = not user_decision.allow
    else:
        if user_decision.source == "fallback":
            global_banned = await run_coro_with_shield(query_user_ban_status_for_gate(uid))
        else:
            global_banned = not user_decision.allow

    if not global_banned and not group_blocked:
        return

    if isinstance(event, FriendRequestEvent):
        if not global_banned:
            return
        try:
            await event.reject(bot)
        except Exception as e:
            logger.warning(f"reject friend request from banned user [{uid}] failed: {e}")
        raise IgnoredException("banned user")

    if isinstance(event, GroupRequestEvent) and event.sub_type == "invite":
        try:
            await event.reject(bot)
        except Exception as e:
            logger.warning(f"reject group invite from banned user [{uid}] failed: {e}")
        raise IgnoredException("banned user")

    logger.debug(f"drop event [{type(event).__name__}] from banned user [{uid}]")
    raise IgnoredException("banned user")
