import json
import os
import tempfile
import time
from pathlib import Path

from nonebot import get_bots, get_driver, logger, on_command, on_message, on_request
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import (
    Bot,
    FriendRequestEvent,
    GroupRequestEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.exception import ActionFailed
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER, Permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot_plugin_apscheduler import scheduler

from src.common.config import BotConfig, GroupConfig, UserConfig
from src.common.paths import plugin_data_dir
from src.plugins.help.plugin_manager import is_plugin_disabled
from src.plugins.request_handler.config import Config

__plugin_meta__ = PluginMetadata(
    name="申请管理",
    description=(
        "处理好友申请与入群邀请：通知管理员，支持命令审批或引用牛牛发出的提醒消息审批；"
        "被过滤好友申请每 4 小时轮询并提醒"
    ),
    usage="""
查看好友申请 — 列出待处理好友（含需单独看的可疑申请）
同意 — 同意最新一条提醒，或引用某条提醒后发送「同意」「好」或留空
同意好友 <QQ> — 同意指定 QQ 的好友申请
同意所有好友 — 同意当前全部好友申请
查看入群邀请 — 列出待处理入群邀请
同意入群 <群号> — 同意指定群的邀请
同意所有入群 — 同意当前全部入群邀请
拒绝入群 <群号> — 拒绝指定群的邀请
查看自动同意 — 查看自动同意开关
开启/关闭自动同意好友 — 切换好友自动同意
开启/关闭自动同意入群 — 切换入群自动同意
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot/Pallas-Bot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "3.0.0",
        "menu_data": [
            {
                "func": "查看待处理申请",
                "trigger_method": "on_cmd",
                "trigger_condition": "查看好友申请 / 查看入群邀请",
                "brief_des": "列出待处理好友与入群邀请",
                "detail_des": "好友列表含被拦截、需单独处理的可疑申请",
            },
            {
                "func": "快捷同意最近申请",
                "trigger_method": "on_cmd",
                "trigger_condition": "同意",
                "brief_des": "快捷同意一条申请",
                "detail_des": "私聊「同意」对应牛牛最新一条提醒；引用某条审批提醒则只处理该条",
            },
            {
                "func": "好友申请审批",
                "trigger_method": "on_cmd",
                "trigger_condition": "同意好友 <QQ号>",
                "brief_des": "按 QQ 同意好友",
                "detail_des": "同意指定 QQ 的好友申请（含普通与可疑申请）",
            },
            {
                "func": "批量审批",
                "trigger_method": "on_cmd",
                "trigger_condition": "同意所有好友 / 同意所有入群",
                "brief_des": "一次性全部同意",
                "detail_des": "同意当前所有待处理好友申请，或所有待处理入群邀请",
            },
            {
                "func": "入群邀请审批",
                "trigger_method": "on_cmd",
                "trigger_condition": "同意入群/拒绝入群 <群号>",
                "brief_des": "按群号同意或拒绝",
                "detail_des": "同意或拒绝指定群的入群邀请",
            },
            {
                "func": "通知开关",
                "trigger_method": "on_cmd",
                "trigger_condition": "牛牛开启/关闭 request_handler",
                "brief_des": "是否推送申请提醒",
                "detail_des": "在帮助系统里开关本插件的好友/入群提醒推送",
            },
            {
                "func": "自动同意开关",
                "trigger_method": "on_cmd",
                "trigger_condition": "查看自动同意 / 开启/关闭自动同意好友 / 开启/关闭自动同意入群",
                "brief_des": "自动同意策略",
                "detail_des": "查看或切换好友申请、入群邀请的自动同意开关",
            },
        ],
        "menu_template": "default",
    },
)

DATA_DIR = plugin_data_dir("request_handler")

FRIEND_REQ_FILE = DATA_DIR / "pending_friend_requests.json"
GROUP_REQ_FILE = DATA_DIR / "pending_group_requests.json"
LAST_NOTIFIED_FILE = DATA_DIR / "last_notified_request.json"
APPROVAL_NOTICE_FILE = DATA_DIR / "approval_notice_messages.json"
DOUBT_POLL_STATE_FILE = DATA_DIR / "doubt_friend_poll_state.json"

PLUGIN_NAME = "request_handler"

# 审批提醒元数据：超过此时长视为过期，不再用于「同意」与引用回复（秒）
_NOTIFY_RECORD_MAX_AGE_SEC = 7 * 24 * 3600

RH_HELP_CMD = "牛牛帮助 request_handler"
RH_APPROVE_HINT = "通过：引用本条，发送「同意」「好」或留空；或直接私聊发送「同意」（按最新一条提醒）"
RH_HELP_HINT = f"帮助：{RH_HELP_CMD}"
RH_LIST_TAIL_FRIEND = (
    "怎么操作：\n"
    "• 私聊只发「同意」→ 处理牛牛最新一条好友审批提醒；\n"
    "• 引用某条审批消息后再发 同意 → 只处理那条对应的申请；\n"
    "• 「同意好友 <QQ号>」→ 按号码同意这一条；\n"
    "• 「同意所有好友」→ 当前表里剩余的全部同意。"
)
RH_LIST_TAIL_GROUP = (
    "怎么操作：\n"
    "• 私聊只发「同意」→ 处理牛牛最新一条入群提醒；\n"
    "• 引用某条入群提醒后再发 同意 → 只处理那条邀请；\n"
    "• 「同意入群 <群号>」同意、「拒绝入群 <群号>」拒绝；\n"
    "• 「同意所有入群」→ 当前表里剩余的全部同意。"
)


def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(payload)
        Path(tmp_path).replace(path)
    except Exception:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass
        raise


def load_doubt_poll_state() -> tuple[set[str], dict[str, set[str]]]:
    raw = load_json(DOUBT_POLL_STATE_FILE)
    if not isinstance(raw, dict):
        return set(), {}
    primed: set[str] = set()
    for x in raw.get("primed_bots", []):
        if x is not None:
            primed.add(str(x))
    notified: dict[str, set[str]] = {}
    nr = raw.get("notified")
    if isinstance(nr, dict):
        for bk, uids in nr.items():
            if not isinstance(uids, list):
                continue
            s = {str(u) for u in uids if u is not None and str(u).isdigit()}
            notified[str(bk)] = s
    return primed, notified


def save_doubt_poll_state(primed: set[str], notified: dict[str, set[str]]) -> None:
    payload = {
        "primed_bots": sorted(primed),
        "notified": {k: sorted(v) for k, v in sorted(notified.items())},
    }
    save_json(DOUBT_POLL_STATE_FILE, payload)


def notify_ts_expired(ts: float, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return bool(ts > 0 and now - ts > _NOTIFY_RECORD_MAX_AGE_SEC)


def api_failure_is_request_gone(exc: BaseException) -> bool:
    """协议返回「请求已不存在 / 已失效」等时可移除本地 pending。"""
    if not isinstance(exc, ActionFailed):
        return False
    for arg in exc.args:
        if isinstance(arg, dict):
            if arg.get("retcode") == 120:
                return True
            wording = str(arg.get("wording", ""))
            if any(k in wording for k in ("失效", "过期", "不存在", "已处理", "无效")):
                return True
    return False


def load_last_notified_store() -> tuple[dict[str, dict[str, str | float]], bool]:
    raw = load_json(LAST_NOTIFIED_FILE)
    out: dict[str, dict[str, str | float]] = {}
    dirty = False
    now = time.time()
    if not isinstance(raw, dict):
        return {}, bool(raw)

    dict_rows = sum(1 for v in raw.values() if isinstance(v, dict))
    for bot_key, row in raw.items():
        bk = str(bot_key)
        if not isinstance(row, dict):
            dirty = True
            continue
        kind = row.get("kind")
        target_id = row.get("target_id")
        if kind not in ("friend", "group") or not isinstance(target_id, str) or not target_id.isdigit():
            dirty = True
            continue
        try:
            ts = float(row["ts"])
        except (KeyError, TypeError, ValueError):
            ts = now
            dirty = True
        if notify_ts_expired(ts, now):
            dirty = True
            continue
        out[bk] = {"kind": kind, "target_id": target_id, "ts": ts}

    if len(out) != dict_rows:
        dirty = True
    return out, dirty


def persist_last_notified_store() -> None:
    prune_stale_last_notified_entries()
    save_json(LAST_NOTIFIED_FILE, last_notified_store)


def prune_stale_last_notified_entries() -> bool:
    changed = False
    now = time.time()
    for bk in list(last_notified_store.keys()):
        row = last_notified_store.get(bk)
        if not isinstance(row, dict):
            last_notified_store.pop(bk, None)
            changed = True
            continue
        ts = float(row.get("ts") or 0)
        if notify_ts_expired(ts, now):
            last_notified_store.pop(bk, None)
            changed = True
    return changed


def set_last_notified(bot_key: str, kind: str, target_id: str) -> None:
    last_notified_store[bot_key] = {"kind": kind, "target_id": target_id, "ts": time.time()}
    persist_last_notified_store()


def get_last_notified(bot_key: str) -> tuple[str, str, float] | None:
    row = last_notified_store.get(bot_key)
    if not row:
        return None
    kind = row.get("kind")
    target_id = row.get("target_id")
    if kind not in ("friend", "group") or not isinstance(target_id, str):
        return None
    try:
        ts = float(row.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0.0
    if notify_ts_expired(ts):
        last_notified_store.pop(bot_key, None)
        persist_last_notified_store()
        return None
    return kind, target_id, ts


def load_approval_notice_map() -> tuple[dict[str, dict[str, dict[str, str | float]]], bool]:
    raw = load_json(APPROVAL_NOTICE_FILE)
    out: dict[str, dict[str, dict[str, str | float]]] = {}
    dirty = False
    now = time.time()
    if not isinstance(raw, dict):
        return {}, bool(raw)

    rows_seen = 0
    rows_kept = 0
    for bot_key, msgs in raw.items():
        bk = str(bot_key)
        if not isinstance(msgs, dict):
            dirty = True
            continue
        inner: dict[str, dict[str, str | float]] = {}
        for mid, row in msgs.items():
            rows_seen += 1
            if not isinstance(row, dict):
                dirty = True
                continue
            kind = row.get("kind")
            tid = row.get("target_id")
            if kind not in ("friend", "group") or not isinstance(tid, str) or not tid.isdigit():
                dirty = True
                continue
            try:
                ts = float(row["ts"])
            except (KeyError, TypeError, ValueError):
                ts = now
                dirty = True
            if notify_ts_expired(ts, now):
                dirty = True
                continue
            inner[str(mid)] = {"kind": kind, "target_id": tid, "ts": ts}
            rows_kept += 1
        if inner:
            out[bk] = inner
        elif msgs:
            dirty = True

    if rows_kept != rows_seen:
        dirty = True
    return out, dirty


def prune_stale_approval_notice_entries() -> bool:
    changed = False
    now = time.time()
    for bk in list(approval_notice_map.keys()):
        inner = approval_notice_map.get(bk)
        if not inner:
            approval_notice_map.pop(bk, None)
            continue
        for mid in list(inner.keys()):
            meta = inner.get(mid)
            if not isinstance(meta, dict):
                inner.pop(mid, None)
                changed = True
                continue
            ts = float(meta.get("ts") or 0)
            if notify_ts_expired(ts, now):
                inner.pop(mid)
                changed = True
        if not inner:
            approval_notice_map.pop(bk, None)
            changed = True
    return changed


def persist_approval_notice_map() -> None:
    prune_stale_approval_notice_entries()
    save_json(APPROVAL_NOTICE_FILE, approval_notice_map)


def register_approval_notice(bot_key: str, message_id: int, kind: str, target_id: str, *, persist: bool = True) -> None:
    approval_notice_map.setdefault(bot_key, {})[str(message_id)] = {
        "kind": kind,
        "target_id": target_id,
        "ts": time.time(),
    }
    if persist:
        persist_approval_notice_map()


def extract_message_id(result: object) -> int | None:
    if result is None:
        return None
    raw_id = result.get("message_id") if isinstance(result, dict) else getattr(result, "message_id", None)
    if raw_id is None:
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def clear_quick_approve_state(bot_key: str, kind: str, target_id: str) -> None:
    ln_changed = False
    row = last_notified_store.get(bot_key)
    if isinstance(row, dict) and row.get("kind") == kind and str(row.get("target_id")) == str(target_id):
        last_notified_store.pop(bot_key, None)
        ln_changed = True
    notice_changed = False
    bot_msgs = approval_notice_map.get(bot_key)
    if bot_msgs:
        for mid in list(bot_msgs.keys()):
            meta = bot_msgs.get(mid)
            if meta and meta.get("kind") == kind and meta.get("target_id") == target_id:
                bot_msgs.pop(mid, None)
                notice_changed = True
        if not bot_msgs:
            approval_notice_map.pop(bot_key, None)
    if ln_changed:
        persist_last_notified_store()
    if notice_changed:
        persist_approval_notice_map()


# {bot_id: {user_id: flag}}
pending_friend: dict[str, dict[str, str]] = load_json(FRIEND_REQ_FILE)
# 被过滤的好友申请 {bot_id: {user_id: flag}}
cached_doubt_friend: dict[str, dict[str, str]] = {}
# {bot_id: {group_id: {...}}}
pending_group: dict[str, dict[str, dict]] = load_json(GROUP_REQ_FILE)
# 最近一次推送：bot_id -> { kind, target_id, ts }，用于「同意」快捷审批
_last_loaded_ln, _last_notified_dirty = load_last_notified_store()
last_notified_store: dict[str, dict[str, str | float]] = _last_loaded_ln
# 审批通知 message_id：bot_id -> { message_id_str -> { kind, target_id, ts } }，用于引用回复处理对应申请
_last_loaded_an, _approval_notice_dirty = load_approval_notice_map()
approval_notice_map: dict[str, dict[str, dict[str, str | float]]] = _last_loaded_an
if _last_notified_dirty:
    save_json(LAST_NOTIFIED_FILE, last_notified_store)
if _approval_notice_dirty:
    save_json(APPROVAL_NOTICE_FILE, approval_notice_map)

# 引用审批通知时允许的正文（小写比较）；空字符串表示仅引用不打字
_APPROVE_REPLY_TEXT = frozenset({"", "同意", "好", "yes", "y", "ok"})


async def fetch_doubt_friends(bot: Bot) -> dict[str, str]:
    """获取被过滤的好友申请"""
    try:
        result = await bot.call_api("get_doubt_friends_add_request", count=50)
        if isinstance(result, list):
            return {str(item["user_id"]): item["flag"] for item in result}
    except Exception:
        pass
    return {}


async def get_nickname(bot: Bot, user_id: int) -> str:
    try:
        info = await bot.call_api("get_stranger_info", user_id=user_id)
        return info.get("nickname", str(user_id))
    except Exception:
        return str(user_id)


async def get_group_name(bot: Bot, group_id: int) -> str:
    try:
        info = await bot.call_api("get_group_info", group_id=group_id)
        return info.get("group_name", str(group_id))
    except Exception:
        pass
    try:
        sys_msg = await bot.call_api("get_group_system_msg")
        all_reqs = (sys_msg.get("join_requests") or []) + (sys_msg.get("invited_requests") or [])
        for req in all_reqs:
            if req.get("group_id") == group_id:
                name = req.get("group_name", "")
                if name:
                    return name
    except Exception:
        pass
    return str(group_id)


async def approve_friend_by_uid(bot: Bot, bot_key: str, uid_str: str) -> tuple[bool, str]:
    bot_pending = pending_friend.get(bot_key, {})
    flag = bot_pending.get(uid_str)
    if flag:
        await bot.set_friend_add_request(flag=flag, approve=True)
        bot_pending.pop(uid_str, None)
        save_json(FRIEND_REQ_FILE, pending_friend)
        nickname = await get_nickname(bot, int(uid_str))
        return True, f"已同意好友：{nickname}（{uid_str}）"

    doubt_cache = cached_doubt_friend.get(bot_key) or await fetch_doubt_friends(bot)
    cached_doubt_friend[bot_key] = doubt_cache
    doubt_flag = doubt_cache.get(uid_str)
    if not doubt_flag:
        nickname = await get_nickname(bot, int(uid_str))
        return False, f"未找到待处理申请：{nickname}（{uid_str}）"

    await bot.call_api("set_doubt_friends_add_request", flag=doubt_flag, approve=True)
    cached_doubt_friend[bot_key].pop(uid_str, None)
    nickname = await get_nickname(bot, int(uid_str))
    return True, f"已同意好友：{nickname}（{uid_str}）"


async def approve_group_invite_by_gid(bot: Bot, bot_key: str, group_key: str) -> tuple[bool, str]:
    bot_pending = pending_group.get(bot_key, {})
    req = bot_pending.get(group_key)
    group_id = int(group_key)
    if not req:
        group_name = await get_group_name(bot, group_id)
        return False, f"未找到待处理邀请：{group_name}（{group_id}）"

    try:
        await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=True)
    except ActionFailed as e:
        if api_failure_is_request_gone(e):
            bot_pending.pop(group_key, None)
            save_json(GROUP_REQ_FILE, pending_group)
            return False, f"失败：{e}（请求失效或已处理）"
        return False, f"操作未成功：{e}（请稍后重试）"
    except Exception as e:
        return False, f"操作未成功：{e}（请稍后重试）"
    bot_pending.pop(group_key, None)
    save_json(GROUP_REQ_FILE, pending_group)
    nickname = await get_nickname(bot, req["user_id"])
    group_name = await get_group_name(bot, group_id)
    return True, f"已同意入群邀请：{group_name}（{group_id}），邀请人 {nickname}（{req['user_id']}）"


request_cmd = on_request(priority=14, block=False)

list_friends_cmd = on_command("查看好友申请", priority=5, block=True)
approve_latest_cmd = on_command("同意", priority=5, block=True)
approve_friend_cmd = on_command("同意好友", priority=5, block=True)
approve_all_friends_cmd = on_command("同意所有好友", priority=5, block=True)
list_groups_cmd = on_command("查看入群邀请", priority=5, block=True)
approve_group_cmd = on_command("同意入群", priority=5, block=True)
approve_all_groups_cmd = on_command("同意所有入群", priority=5, block=True)
reject_group_cmd = on_command("拒绝入群", priority=5, block=True)
auto_accept_status_cmd = on_command("查看自动同意", priority=5, block=True)
enable_auto_friend_cmd = on_command("开启自动同意好友", priority=5, block=True)
disable_auto_friend_cmd = on_command("关闭自动同意好友", priority=5, block=True)
enable_auto_group_cmd = on_command("开启自动同意入群", priority=5, block=True)
disable_auto_group_cmd = on_command("关闭自动同意入群", priority=5, block=True)


async def is_bot_admin(bot: Bot, event: MessageEvent) -> bool:
    admins = await BotConfig(int(bot.self_id))._find("admins")
    return event.user_id in admins


BOT_ADMIN = Permission(is_bot_admin)
PERM = SUPERUSER | BOT_ADMIN


def plugin_config() -> Config:
    return Config.model_validate(get_driver().config.model_dump())


async def notify_admins(bot: Bot, msg: str, *, kind: str, target_id: str) -> bool:
    bot_key = str(bot.self_id)
    admins = await BotConfig(int(bot.self_id))._find("admins")
    plugin_cfg = plugin_config()
    if not plugin_cfg.request_handler_notify_superusers:
        superusers = {int(uid) for uid in get_driver().config.superusers}
        # 过滤掉 SUPERUSER，若全部都是 SUPERUSER 则发送给SUPERUSER
        admins = [uid for uid in admins if uid not in superusers] or admins
    registered = False
    delivered_any = False
    for admin_id in admins:
        try:
            ret = await bot.send_private_msg(user_id=admin_id, message=msg)
            delivered_any = True
            mid = extract_message_id(ret)
            if mid is not None:
                register_approval_notice(bot_key, mid, kind, target_id, persist=False)
                registered = True
        except Exception:
            pass
    if registered:
        persist_approval_notice_map()
    return delivered_any


@scheduler.scheduled_job(
    "interval",
    hours=4,
    id="request_handler_poll_doubt_friends",
    coalesce=True,
    max_instances=1,
)
async def poll_doubt_friends_job() -> None:
    if not plugin_config().request_handler_poll_doubt_friends:
        return
    primed_bots, notified_map = load_doubt_poll_state()
    state_updated = False
    for bot in get_bots().values():
        if not isinstance(bot, Bot):
            continue
        bot_id = int(bot.self_id)
        bot_key = str(bot_id)
        if await is_plugin_disabled(PLUGIN_NAME, bot_id=bot_id):
            continue
        try:
            doubts = await fetch_doubt_friends(bot)
        except Exception as e:
            logger.debug(f"poll doubt friends call_api failed bot={bot_key}: {e}")
            continue
        cached_doubt_friend[bot_key] = doubts
        current_uids = set(doubts.keys())
        pending_keys = pending_friend.get(bot_key, {})

        if bot_key not in primed_bots:
            notified_map[bot_key] = set(current_uids)
            primed_bots.add(bot_key)
            state_updated = True
            continue

        notified_set = notified_map.setdefault(bot_key, set())
        before_prune = frozenset(notified_set)
        notified_set &= current_uids
        if before_prune != frozenset(notified_set):
            state_updated = True

        for uid in sorted(current_uids):
            if uid in pending_keys:
                continue
            if uid in notified_set:
                continue
            nickname = await get_nickname(bot, int(uid))
            msg = f"[好友申请·被过滤]\n申请人：{nickname}（{uid}）\n{RH_APPROVE_HINT}\n{RH_HELP_HINT}"
            if await notify_admins(bot, msg, kind="friend", target_id=uid):
                set_last_notified(bot_key, "friend", uid)
                notified_set.add(uid)
                state_updated = True
            else:
                logger.warning(f"未能推送被过滤好友提醒 bot={bot_key} uid={uid}")

        notified_map[bot_key] = notified_set

    if state_updated:
        save_doubt_poll_state(primed_bots, notified_map)


async def approval_reply_rule(bot: Bot, event: Event) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False
    if not await PERM(bot, event):
        return False
    if not event.reply:
        return False
    bot_key = str(bot.self_id)
    mid = str(event.reply.message_id)
    bot_msgs = approval_notice_map.get(bot_key)
    if not bot_msgs or mid not in bot_msgs:
        return False
    meta = bot_msgs[mid]
    ts = float(meta.get("ts") or 0)
    if ts and notify_ts_expired(ts):
        bot_msgs.pop(mid, None)
        if not bot_msgs:
            approval_notice_map.pop(bot_key, None)
        persist_approval_notice_map()
        return False
    return True


approval_reply_cmd = on_message(rule=Rule(approval_reply_rule), priority=4, block=True)


@approval_reply_cmd.handle()
async def handle_approval_reply(bot: Bot, event: PrivateMessageEvent):
    bot_key = str(bot.self_id)
    mid = str(event.reply.message_id)
    meta = approval_notice_map.get(bot_key, {}).get(mid)
    if not meta:
        return
    text = event.get_plaintext().strip().lower()
    if text not in _APPROVE_REPLY_TEXT:
        await approval_reply_cmd.finish("引用审批消息后，正文须为：同意 / 好 / 留空。")
    kind = str(meta["kind"])
    target_id = str(meta["target_id"])
    if kind == "friend":
        ok, msg = await approve_friend_by_uid(bot, bot_key, target_id)
    else:
        ok, msg = await approve_group_invite_by_gid(bot, bot_key, target_id)
    if ok:
        clear_quick_approve_state(bot_key, kind, target_id)
    await approval_reply_cmd.finish(msg)


@request_cmd.handle()
async def handle_friend_request(bot: Bot, event: FriendRequestEvent):
    bot_id = int(bot.self_id)
    bot_key = str(bot_id)
    pending_friend.setdefault(bot_key, {})[str(event.user_id)] = event.flag
    save_json(FRIEND_REQ_FILE, pending_friend)

    bot_config = BotConfig(bot_id)
    if await bot_config.auto_accept_friend():
        await event.approve(bot)
        pending_friend.get(bot_key, {}).pop(str(event.user_id), None)
        save_json(FRIEND_REQ_FILE, pending_friend)
        return

    if not await is_plugin_disabled(PLUGIN_NAME, bot_id=bot_id):
        nickname = await get_nickname(bot, event.user_id)
        msg = (
            f"[好友申请]\n"
            f"申请人：{nickname}（{event.user_id}）\n"
            f"验证：{event.comment or '-'}\n"
            f"{RH_APPROVE_HINT}\n"
            f"{RH_HELP_HINT}"
        )
        if await notify_admins(bot, msg, kind="friend", target_id=str(event.user_id)):
            set_last_notified(bot_key, "friend", str(event.user_id))


@list_friends_cmd.handle()
async def handle_list_friends(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_friend.get(bot_key, {})

    # 获取被过滤的好友申请并缓存
    doubt_requests = await fetch_doubt_friends(bot)
    cached_doubt_friend[bot_key] = doubt_requests

    # 去重：被过滤列表中已在普通列表的不重复计数
    doubt_only = {uid: flag for uid, flag in doubt_requests.items() if uid not in bot_pending}
    total = len(bot_pending) + len(doubt_only)
    if total == 0:
        await list_friends_cmd.finish("暂无待处理好友申请")

    lines = [f"待处理好友申请（共 {total} 条）："]
    for uid in bot_pending.keys():
        nickname = await get_nickname(bot, int(uid))
        lines.append(f"  {nickname}（{uid}）")
    for uid in doubt_only.keys():
        nickname = await get_nickname(bot, int(uid))
        lines.append(f"  {nickname}（{uid}）[被过滤]")
    lines.append(RH_LIST_TAIL_FRIEND)
    await list_friends_cmd.finish("\n".join(lines))


@approve_latest_cmd.handle()
async def handle_approve_latest(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await PERM(bot, event):
        return
    arg = args.extract_plain_text().strip()
    if arg:
        await approve_latest_cmd.finish(
            "单独发送「同意」时不要跟其它内容；带号码请用「同意好友」「同意入群」。"
            "若要同意较早一条提醒，请引用那条提醒后再操作。"
        )
    bot_key = str(bot.self_id)
    entry = get_last_notified(bot_key)
    if not entry:
        await approve_latest_cmd.finish("没有可用的「最新一条」提醒；请先查看列表或使用带 QQ 号、群号的同意命令。")
    kind, target_id, _ts = entry
    if kind == "friend":
        ok, msg = await approve_friend_by_uid(bot, bot_key, target_id)
    else:
        ok, msg = await approve_group_invite_by_gid(bot, bot_key, target_id)
    if ok:
        clear_quick_approve_state(bot_key, kind, target_id)
    await approve_latest_cmd.finish(msg)


@approve_friend_cmd.handle()
async def handle_approve_friend(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await PERM(bot, event):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await approve_friend_cmd.finish("格式：同意好友 <QQ号>")

    bot_key = str(bot.self_id)
    ok, msg = await approve_friend_by_uid(bot, bot_key, arg)
    if ok:
        clear_quick_approve_state(bot_key, "friend", arg)
    await approve_friend_cmd.finish(msg)


@list_groups_cmd.handle()
async def handle_list_groups(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_group.get(bot_key, {})
    if not bot_pending:
        await list_groups_cmd.finish("暂无待处理入群邀请")
    lines = [f"待处理入群邀请（共 {len(bot_pending)} 条）："]
    for group_key, req in bot_pending.items():
        nickname = await get_nickname(bot, req["user_id"])
        group_name = await get_group_name(bot, int(group_key))
        lines.append(f"  {group_name}（{group_key}）← {nickname}（{req['user_id']}）邀请")
    lines.append(RH_LIST_TAIL_GROUP)
    await list_groups_cmd.finish("\n".join(lines))


@request_cmd.handle()
async def handle_group_request(bot: Bot, event: GroupRequestEvent):
    if event.sub_type == "invite":
        if await GroupConfig(event.group_id).is_banned() or await UserConfig(event.user_id).is_banned():
            await event.reject(bot)
            return

        bot_id = int(bot.self_id)
        bot_key = str(bot_id)
        group_key = str(event.group_id)
        pending_group.setdefault(bot_key, {})[group_key] = {
            "flag": event.flag,
            "sub_type": "invite",
            "user_id": event.user_id,
            "group_id": event.group_id,
            "comment": event.comment or "",
        }
        save_json(GROUP_REQ_FILE, pending_group)

        bot_config = BotConfig(bot_id)
        if await bot_config.auto_accept_group() or await bot_config.is_admin_of_bot(event.user_id):
            await event.approve(bot)
            pending_group.get(bot_key, {}).pop(group_key, None)
            save_json(GROUP_REQ_FILE, pending_group)
            return

        if not await is_plugin_disabled(PLUGIN_NAME, bot_id=bot_id):
            nickname = await get_nickname(bot, event.user_id)
            group_name = await get_group_name(bot, event.group_id)
            msg = (
                f"[入群邀请]\n"
                f"邀请人：{nickname}（{event.user_id}）\n"
                f"群：{group_name}（{event.group_id}）\n"
                f"{RH_APPROVE_HINT}\n"
                f"拒绝：拒绝入群 {event.group_id}\n"
                f"{RH_HELP_HINT}"
            )
            if await notify_admins(bot, msg, kind="group", target_id=group_key):
                set_last_notified(bot_key, "group", group_key)


@approve_all_friends_cmd.handle()
async def handle_approve_all_friends(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_friend.get(bot_key, {})
    doubt_requests = await fetch_doubt_friends(bot)
    cached_doubt_friend[bot_key] = doubt_requests

    if not bot_pending and not doubt_requests:
        await approve_all_friends_cmd.finish("暂无待处理好友申请")

    ok, fail = 0, 0
    cleared_friend_ids: set[str] = set()
    for uid, flag in list(bot_pending.items()):
        try:
            await bot.set_friend_add_request(flag=flag, approve=True)
            bot_pending.pop(uid, None)
            ok += 1
            cleared_friend_ids.add(uid)
        except Exception:
            fail += 1
    save_json(FRIEND_REQ_FILE, pending_friend)

    for uid, flag in list(doubt_requests.items()):
        try:
            await bot.call_api("set_doubt_friends_add_request", flag=flag, approve=True)
            cached_doubt_friend[bot_key].pop(uid, None)
            ok += 1
            cleared_friend_ids.add(uid)
        except Exception:
            fail += 1

    for uid in cleared_friend_ids:
        clear_quick_approve_state(bot_key, "friend", uid)

    await approve_all_friends_cmd.finish(f"已同意 {ok} 条好友申请" + (f"，{fail} 条失败" if fail else ""))


@approve_all_groups_cmd.handle()
async def handle_approve_all_groups(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_group.get(bot_key, {})
    if not bot_pending:
        await approve_all_groups_cmd.finish("暂无待处理入群邀请")
    ok, fail = 0, 0
    cleared_group_keys: set[str] = set()
    for key, req in list(bot_pending.items()):
        try:
            await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=True)
            bot_pending.pop(key, None)
            ok += 1
            cleared_group_keys.add(key)
        except Exception:
            fail += 1
    save_json(GROUP_REQ_FILE, pending_group)
    for gkey in cleared_group_keys:
        clear_quick_approve_state(bot_key, "group", gkey)
    await approve_all_groups_cmd.finish(f"已同意 {ok} 条入群邀请" + (f"，{fail} 条失败" if fail else ""))


@approve_group_cmd.handle()
async def handle_approve_group(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await PERM(bot, event):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await approve_group_cmd.finish("格式：同意入群 <群号>")

    bot_key = str(bot.self_id)
    group_key = str(int(arg))
    ok, msg = await approve_group_invite_by_gid(bot, bot_key, group_key)
    if ok:
        clear_quick_approve_state(bot_key, "group", group_key)
    await approve_group_cmd.finish(msg)


@auto_accept_status_cmd.handle()
async def handle_auto_accept_status(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    bot_config = BotConfig(int(bot.self_id))
    friend_on = await bot_config.auto_accept_friend()
    group_on = await bot_config.auto_accept_group()
    friend_str = "✅ 开启" if friend_on else "❌ 关闭"
    group_str = "✅ 开启" if group_on else "❌ 关闭"
    await auto_accept_status_cmd.finish(
        f"好友自动同意：{friend_str}\n入群自动同意：{group_str}\n切换：开启/关闭 自动同意好友、自动同意入群"
    )


@enable_auto_friend_cmd.handle()
async def handle_enable_auto_friend(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_friend(True)
    await enable_auto_friend_cmd.finish("已开启好友自动同意")


@disable_auto_friend_cmd.handle()
async def handle_disable_auto_friend(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_friend(False)
    await disable_auto_friend_cmd.finish("已关闭好友自动同意")


@enable_auto_group_cmd.handle()
async def handle_enable_auto_group(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_group(True)
    await enable_auto_group_cmd.finish("已开启入群自动同意")


@disable_auto_group_cmd.handle()
async def handle_disable_auto_group(bot: Bot, event: MessageEvent):
    if not await PERM(bot, event):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_group(False)
    await disable_auto_group_cmd.finish("已关闭入群自动同意")


@reject_group_cmd.handle()
async def handle_reject_group(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await PERM(bot, event):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await reject_group_cmd.finish("格式：拒绝入群 <群号>")

    bot_key = str(bot.self_id)
    group_id = int(arg)
    group_key = str(group_id)
    bot_pending = pending_group.get(bot_key, {})
    req = bot_pending.get(group_key)
    if not req:
        group_name = await get_group_name(bot, group_id)
        await reject_group_cmd.finish(f"未找到待处理邀请：{group_name}（{group_id}）")

    try:
        await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=False)
    except ActionFailed as e:
        if api_failure_is_request_gone(e):
            bot_pending.pop(group_key, None)
            save_json(GROUP_REQ_FILE, pending_group)
            await reject_group_cmd.finish(f"失败：{e}（请求失效或已处理）")
            return
        await reject_group_cmd.finish(f"操作未成功：{e}（请稍后重试）")
        return
    except Exception as e:
        await reject_group_cmd.finish(f"操作未成功：{e}（请稍后重试）")
        return
    bot_pending.pop(group_key, None)
    save_json(GROUP_REQ_FILE, pending_group)
    clear_quick_approve_state(bot_key, "group", group_key)
    nickname = await get_nickname(bot, req["user_id"])
    group_name = await get_group_name(bot, group_id)
    await reject_group_cmd.finish(f"已拒绝入群邀请：{group_name}（{group_id}），邀请人 {nickname}（{req['user_id']}）")
