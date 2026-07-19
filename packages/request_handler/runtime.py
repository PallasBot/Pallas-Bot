import time
from pathlib import Path

from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import Bot
from nonebot.exception import ActionFailed

from packages.request_handler.config import Config
from packages.request_handler.storage import (
    load_json_file,
    merge_write_bot_entry,
    merge_write_bot_nested_entries,
    save_json_file,
)
from pallas.core.foundation.config import get_bot_admins
from pallas.core.foundation.paths import plugin_data_dir

PLUGIN_NAME = "request_handler"

DATA_DIR = plugin_data_dir("request_handler")

FRIEND_REQ_FILE = DATA_DIR / "pending_friend_requests.json"
GROUP_REQ_FILE = DATA_DIR / "pending_group_requests.json"
LAST_NOTIFIED_FILE = DATA_DIR / "last_notified_request.json"
APPROVAL_NOTICE_FILE = DATA_DIR / "approval_notice_messages.json"
DOUBT_POLL_STATE_FILE = DATA_DIR / "doubt_friend_poll_state.json"

# 审批提醒元数据：超过此时长视为过期，不再用于「同意/拒绝」与引用回复
_NOTIFY_RECORD_MAX_AGE_SEC = 7 * 24 * 3600


def load_json(path: Path) -> dict:
    return load_json_file(path)


def save_json(path: Path, data: dict) -> None:
    save_json_file(path, data)


def persist_pending_friend(bot_key: str) -> None:
    merge_write_bot_nested_entries(FRIEND_REQ_FILE, pending_friend, bot_key)


def persist_pending_group(bot_key: str) -> None:
    merge_write_bot_nested_entries(GROUP_REQ_FILE, pending_group, bot_key)


def persist_last_notified_bot(bot_key: str) -> None:
    merge_write_bot_entry(LAST_NOTIFIED_FILE, last_notified_store, bot_key)


def persist_approval_notice_bot(bot_key: str) -> None:
    merge_write_bot_nested_entries(APPROVAL_NOTICE_FILE, approval_notice_map, bot_key)


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
    """协议返回「请求已不存在 / 已失效」等。"""
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


def failure_cleanup_friend(bot_key: str, uid_str: str) -> None:
    """协议调用失败后移除本地好友 pending，避免失效记录占位。"""
    bot_pending = pending_friend.get(bot_key)
    if bot_pending and uid_str in bot_pending:
        bot_pending.pop(uid_str, None)
        persist_pending_friend(bot_key)
    doubt_cache = cached_doubt_friend.get(bot_key)
    if doubt_cache and uid_str in doubt_cache:
        doubt_cache.pop(uid_str, None)
    clear_quick_approve_state(bot_key, "friend", uid_str)


def failure_cleanup_group(bot_key: str, group_key: str) -> None:
    """协议调用失败后移除本地入群 pending，避免失效记录占位。"""
    bot_pending = pending_group.get(bot_key)
    if bot_pending and group_key in bot_pending:
        bot_pending.pop(group_key, None)
        persist_pending_group(bot_key)
    clear_quick_approve_state(bot_key, "group", group_key)


def api_failure_user_message(exc: ActionFailed) -> str:
    suffix = "（请求失效或已处理）" if api_failure_is_request_gone(exc) else "（已从待处理列表移除）"
    return f"失败：{exc}{suffix}"


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


def persist_last_notified_store(bot_key: str | None = None) -> None:
    prune_stale_last_notified_entries()
    if bot_key is not None:
        persist_last_notified_bot(bot_key)
        return

    for current_bot_key in list(last_notified_store.keys()):
        persist_last_notified_bot(current_bot_key)

    disk_data = load_json(LAST_NOTIFIED_FILE)
    stale_keys = [str(key) for key in disk_data.keys() if str(key) not in last_notified_store]
    if stale_keys:
        for stale_bot_key in stale_keys:
            last_notified_store.pop(stale_bot_key, None)
            persist_last_notified_bot(stale_bot_key)


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
    persist_last_notified_store(bot_key)


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
        persist_last_notified_store(bot_key)
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


def persist_approval_notice_map(bot_key: str | None = None) -> None:
    prune_stale_approval_notice_entries()
    if bot_key is not None:
        persist_approval_notice_bot(bot_key)
        return

    for current_bot_key in list(approval_notice_map.keys()):
        persist_approval_notice_bot(current_bot_key)

    disk_data = load_json(APPROVAL_NOTICE_FILE)
    stale_keys = [str(key) for key in disk_data.keys() if str(key) not in approval_notice_map]
    if stale_keys:
        for stale_bot_key in stale_keys:
            approval_notice_map.pop(stale_bot_key, None)
            persist_approval_notice_bot(stale_bot_key)


def register_approval_notice(bot_key: str, message_id: int, kind: str, target_id: str, *, persist: bool = True) -> None:
    approval_notice_map.setdefault(bot_key, {})[str(message_id)] = {
        "kind": kind,
        "target_id": target_id,
        "ts": time.time(),
    }
    if persist:
        persist_approval_notice_map(bot_key)


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
        persist_last_notified_store(bot_key)
    if notice_changed:
        persist_approval_notice_map(bot_key)


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


def rows_from_doubt_friends_api(result: object) -> list[dict]:
    if isinstance(result, list):
        return [x for x in result if isinstance(x, dict)]
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    return []


def uid_flag_from_doubt_friend_row(item: dict) -> tuple[str, str] | None:
    flag = item.get("flag")
    if flag is None:
        return None
    flag_str = str(flag).strip()
    if not flag_str:
        return None
    uid_raw = item.get("user_id")
    if uid_raw is None:
        uid_raw = item.get("uin")
    if uid_raw is None:
        return None
    uid_str = str(uid_raw).strip()
    if not uid_str:
        return None
    return uid_str, flag_str


async def fetch_doubt_friends(bot: Bot) -> dict[str, str]:
    """获取被过滤的好友申请"""
    try:
        result = await bot.call_api("get_doubt_friends_add_request", count=50)
        out: dict[str, str] = {}
        for item in rows_from_doubt_friends_api(result):
            pair = uid_flag_from_doubt_friend_row(item)
            if pair is None:
                continue
            uid_str, flag_str = pair
            out[uid_str] = flag_str
        return out
    except Exception as e:
        logger.debug(f"bot [{int(bot.self_id)}] get_doubt_friends_add_request failed: {e}")
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
        try:
            await bot.set_friend_add_request(flag=flag, approve=True)
        except ActionFailed as e:
            failure_cleanup_friend(bot_key, uid_str)
            return False, api_failure_user_message(e)
        except Exception as e:
            return False, f"操作未成功：{e}（请稍后重试）"
        bot_pending.pop(uid_str, None)
        persist_pending_friend(bot_key)
        nickname = await get_nickname(bot, int(uid_str))
        return True, f"已同意好友：{nickname}（{uid_str}）"

    doubt_cache = cached_doubt_friend.get(bot_key) or await fetch_doubt_friends(bot)
    cached_doubt_friend[bot_key] = doubt_cache
    doubt_flag = doubt_cache.get(uid_str)
    if not doubt_flag:
        nickname = await get_nickname(bot, int(uid_str))
        return False, f"未找到待处理申请：{nickname}（{uid_str}）"

    try:
        await bot.call_api("set_doubt_friends_add_request", flag=doubt_flag, approve=True)
    except ActionFailed as e:
        failure_cleanup_friend(bot_key, uid_str)
        return False, api_failure_user_message(e)
    except Exception as e:
        return False, f"操作未成功：{e}（请稍后重试）"
    cached_doubt_friend[bot_key].pop(uid_str, None)
    nickname = await get_nickname(bot, int(uid_str))
    return True, f"已同意好友：{nickname}（{uid_str}）"


async def reject_friend_by_uid(bot: Bot, bot_key: str, uid_str: str) -> tuple[bool, str]:
    bot_pending = pending_friend.get(bot_key, {})
    flag = bot_pending.get(uid_str)
    if flag:
        try:
            await bot.set_friend_add_request(flag=flag, approve=False)
        except ActionFailed as e:
            failure_cleanup_friend(bot_key, uid_str)
            return False, api_failure_user_message(e)
        except Exception as e:
            return False, f"操作未成功：{e}（请稍后重试）"
        bot_pending.pop(uid_str, None)
        persist_pending_friend(bot_key)
        nickname = await get_nickname(bot, int(uid_str))
        return True, f"已拒绝好友：{nickname}（{uid_str}）"

    doubt_cache = cached_doubt_friend.get(bot_key) or await fetch_doubt_friends(bot)
    cached_doubt_friend[bot_key] = doubt_cache
    doubt_flag = doubt_cache.get(uid_str)
    if not doubt_flag:
        nickname = await get_nickname(bot, int(uid_str))
        return False, f"未找到待处理申请：{nickname}（{uid_str}）"

    try:
        await bot.call_api("set_doubt_friends_add_request", flag=doubt_flag, approve=False)
    except ActionFailed as e:
        failure_cleanup_friend(bot_key, uid_str)
        return False, api_failure_user_message(e)
    except Exception as e:
        return False, f"操作未成功：{e}（请稍后重试）"
    cached_doubt_friend[bot_key].pop(uid_str, None)
    nickname = await get_nickname(bot, int(uid_str))
    return True, f"已拒绝好友：{nickname}（{uid_str}）"


async def approve_group_invite_by_gid(bot: Bot, bot_key: str, group_key: str) -> tuple[bool, str]:
    bot_pending = pending_group.get(bot_key, {})
    req = bot_pending.get(group_key)
    group_id = int(group_key)
    if not req:
        group_name = await get_group_name(bot, group_id)
        return False, f"未找到待处理入群申请：{group_name}（{group_id}）"

    try:
        await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=True)
    except ActionFailed as e:
        failure_cleanup_group(bot_key, group_key)
        return False, api_failure_user_message(e)
    except Exception as e:
        return False, f"操作未成功：{e}（请稍后重试）"
    bot_pending.pop(group_key, None)
    persist_pending_group(bot_key)
    nickname = await get_nickname(bot, req["user_id"])
    group_name = await get_group_name(bot, group_id)
    return True, f"已同意入群申请：{group_name}（{group_id}），邀请人 {nickname}（{req['user_id']}）"


async def reject_group_invite_by_gid(bot: Bot, bot_key: str, group_key: str) -> tuple[bool, str]:
    bot_pending = pending_group.get(bot_key, {})
    req = bot_pending.get(group_key)
    group_id = int(group_key)
    if not req:
        group_name = await get_group_name(bot, group_id)
        return False, f"未找到待处理入群申请：{group_name}（{group_id}）"

    try:
        await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=False)
    except ActionFailed as e:
        failure_cleanup_group(bot_key, group_key)
        return False, api_failure_user_message(e)
    except Exception as e:
        return False, f"操作未成功：{e}（请稍后重试）"
    bot_pending.pop(group_key, None)
    persist_pending_group(bot_key)
    nickname = await get_nickname(bot, req["user_id"])
    group_name = await get_group_name(bot, group_id)
    return True, f"已拒绝入群申请：{group_name}（{group_id}），邀请人 {nickname}（{req['user_id']}）"


async def request_handler_plugin_disabled(*, bot_id: int) -> bool:
    from packages.help.plugin_manager import is_plugin_disabled

    return await is_plugin_disabled(PLUGIN_NAME, bot_id=bot_id)


def plugin_config() -> Config:
    from .config import get_request_handler_config

    return get_request_handler_config()


async def notify_admins(bot: Bot, msg: str, *, kind: str, target_id: str) -> bool:
    bot_key = str(bot.self_id)
    admins = await get_bot_admins(int(bot.self_id))
    plugin_cfg = plugin_config()
    if not plugin_cfg.request_handler_notify_superusers:
        superusers = {int(uid) for uid in get_driver().config.superusers}
        admins = [uid for uid in admins if uid not in superusers] or admins
    if not admins:
        admins = [int(uid) for uid in get_driver().config.superusers]
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
        persist_approval_notice_map(bot_key)
    return delivered_any
