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
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot_plugin_apscheduler import scheduler

from src.features.cmd_perm import private_message_permission_for_command, satisfies_command_permission
from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_PRIVATE, join_usage, usage_line
from src.foundation.config import BotConfig, GroupConfig, UserConfig, get_bot_admins, user_is_bot_admin
from src.foundation.paths import plugin_data_dir
from src.plugins.request_handler.approval_notice_text import parse_approval_notice_meta
from src.plugins.request_handler.approval_reply_text import (
    classify_approval_reply_text,
    extract_approval_reply_text_from_body,
)
from src.plugins.request_handler.config import Config
from src.plugins.request_handler.storage import (
    load_json_file,
    merge_write_bot_entry,
    merge_write_bot_nested_entries,
    save_json_file,
)
from src.plugins.request_handler.texts import (
    APPROVE_ALL_FRIENDS_COMMAND,
    APPROVE_ALL_GROUPS_ALIASES,
    APPROVE_ALL_GROUPS_COMMAND,
    APPROVE_FRIEND_COMMAND,
    APPROVE_GROUP_COMMAND,
    APPROVE_LATEST_COMMAND,
    AUTO_ACCEPT_STATUS_ALIASES,
    AUTO_ACCEPT_STATUS_COMMAND,
    DISABLE_AUTO_FRIEND_COMMAND,
    DISABLE_AUTO_GROUP_COMMAND,
    ENABLE_AUTO_FRIEND_COMMAND,
    ENABLE_AUTO_GROUP_COMMAND,
    LIST_FRIEND_ALIASES,
    LIST_FRIEND_COMMAND,
    LIST_GROUP_ALIASES,
    LIST_GROUP_COMMAND,
    REJECT_ALL_FRIENDS_COMMAND,
    REJECT_ALL_GROUPS_ALIASES,
    REJECT_ALL_GROUPS_COMMAND,
    REJECT_FRIEND_COMMAND,
    REJECT_GROUP_COMMAND,
    REJECT_LATEST_COMMAND,
    REQUEST_HANDLER_HELP_HINT,
    REQUEST_HANDLER_USAGE_LINES,
    build_list_tail,
    build_quick_action_arg_hint,
    build_quick_action_missing_hint,
)

PLUGIN_NAME = "request_handler"


async def request_handler_plugin_disabled(*, bot_id: int) -> bool:
    from src.plugins.help.plugin_manager import is_plugin_disabled

    return await is_plugin_disabled(PLUGIN_NAME, bot_id=bot_id)


__plugin_meta__ = PluginMetadata(
    name="申请管理",
    description="好友/入群申请提醒与审批，支持自动同意开关。",
    usage=join_usage(
        *(usage_line(*line.split(" — ", 1)) for line in REQUEST_HANDLER_USAGE_LINES),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "disable_scope": "bot",
        "command_permissions": [
            {"id": "request.list_friends", "label": "查看好友申请", "default": "bot_moderator"},
            {"id": "request.list_groups", "label": "查看入群申请", "default": "bot_moderator"},
            {"id": "request.approve_latest", "label": "同意（快捷）", "default": "bot_moderator"},
            {"id": "request.reject_latest", "label": "拒绝（快捷）", "default": "bot_moderator"},
            {"id": "request.approve_friend", "label": "同意好友", "default": "bot_moderator"},
            {"id": "request.reject_friend", "label": "拒绝好友", "default": "bot_moderator"},
            {"id": "request.approve_all_friends", "label": "同意所有好友", "default": "bot_moderator"},
            {"id": "request.reject_all_friends", "label": "拒绝所有好友", "default": "bot_moderator"},
            {"id": "request.approve_all_groups", "label": "同意所有入群申请", "default": "bot_moderator"},
            {"id": "request.reject_all_groups", "label": "拒绝所有入群申请", "default": "bot_moderator"},
            {"id": "request.approve_group", "label": "同意入群", "default": "bot_moderator"},
            {"id": "request.reject_group", "label": "拒绝入群", "default": "bot_moderator"},
            {"id": "request.auto_accept_status", "label": "查看自动同意", "default": "bot_moderator"},
            {"id": "request.enable_auto_friend", "label": "开启自动同意好友", "default": "bot_moderator"},
            {"id": "request.disable_auto_friend", "label": "关闭自动同意好友", "default": "bot_moderator"},
            {"id": "request.enable_auto_group", "label": "开启自动同意入群", "default": "bot_moderator"},
            {"id": "request.disable_auto_group", "label": "关闭自动同意入群", "default": "bot_moderator"},
            {"id": "request.approval_reply", "label": "引用审批消息快捷同意/拒绝", "default": "bot_moderator"},
        ],
        "menu_data": [
            {
                "func": "查看待处理申请",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "查看好友申请 / 查看入群申请",
                "command_permissions": ["request.list_friends", "request.list_groups"],
                "brief_des": "列出待处理好友与入群申请",
                "detail_des": "好友列表含被拦截、需单独处理的可疑申请；入群列表兼容旧口令“查看入群邀请”",
            },
            {
                "func": "快捷同意最近申请",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "同意",
                "command_permission": "request.approve_latest",
                "brief_des": "快捷同意一条申请",
                "detail_des": "私聊「同意」对应牛牛最新一条提醒；引用某条审批提醒则只处理该条",
            },
            {
                "func": "快捷拒绝最近申请",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "拒绝",
                "command_permission": "request.reject_latest",
                "brief_des": "快捷拒绝一条申请",
                "detail_des": "私聊「拒绝」对应牛牛最新一条提醒；引用某条审批提醒则只处理该条",
            },
            {
                "func": "引用审批消息快捷操作",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "引用审批提醒：同意 / 好 / 留空，或 拒绝 / 不要 / 否",
                "command_permissions": [
                    "request.approval_reply",
                    "request.reject_friend",
                    "request.reject_group",
                ],
                "brief_des": "按引用对应单一申请同意或拒绝",
                "detail_des": "须引用仍有效的审批消息；同意与拒绝分别校验对应命令权限",
            },
            {
                "func": "好友申请审批",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "同意好友 <QQ号>",
                "command_permission": "request.approve_friend",
                "brief_des": "按 QQ 同意好友",
                "detail_des": "同意指定 QQ 的好友申请（含普通与可疑申请）",
            },
            {
                "func": "好友申请拒绝",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "拒绝好友 <QQ号>",
                "command_permission": "request.reject_friend",
                "brief_des": "按 QQ 拒绝好友",
                "detail_des": "拒绝指定 QQ 的好友申请（含普通与可疑申请）",
            },
            {
                "func": "批量审批",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "同意所有好友 / 拒绝所有好友 / 同意所有入群 / 拒绝所有入群",
                "command_permissions": [
                    "request.approve_all_friends",
                    "request.reject_all_friends",
                    "request.approve_all_groups",
                    "request.reject_all_groups",
                ],
                "brief_des": "好友或入群批量同意/拒绝",
                "detail_des": "一次性同意或拒绝当前全部待处理好友申请或入群申请",
            },
            {
                "func": "入群申请审批",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "同意入群 / 拒绝入群 <群号>",
                "command_permissions": ["request.approve_group", "request.reject_group"],
                "brief_des": "按群号同意或拒绝",
                "detail_des": "同意或拒绝指定群的入群申请",
            },
            {
                "func": "通知开关",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "牛牛开启 / 牛牛关闭 申请管理",
                "command_permissions": ["help.plugin_enable", "help.plugin_disable"],
                "brief_des": "是否推送申请提醒",
                "detail_des": "私聊切换本牛是否推送好友/入群申请提醒（单牛全局；审批口令亦在私聊使用）",
            },
            {
                "func": "自动同意开关",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "查看自动同意 / 开启或关闭自动同意好友 / 入群",
                "command_permissions": [
                    "request.auto_accept_status",
                    "request.enable_auto_friend",
                    "request.disable_auto_friend",
                    "request.enable_auto_group",
                    "request.disable_auto_group",
                ],
                "brief_des": "自动同意策略",
                "detail_des": "查看或切换好友申请、入群申请的自动同意开关",
            },
        ],
    },
)

DATA_DIR = plugin_data_dir("request_handler")

FRIEND_REQ_FILE = DATA_DIR / "pending_friend_requests.json"
GROUP_REQ_FILE = DATA_DIR / "pending_group_requests.json"
LAST_NOTIFIED_FILE = DATA_DIR / "last_notified_request.json"
APPROVAL_NOTICE_FILE = DATA_DIR / "approval_notice_messages.json"
DOUBT_POLL_STATE_FILE = DATA_DIR / "doubt_friend_poll_state.json"

# 审批提醒元数据：超过此时长视为过期，不再用于「同意/拒绝」与引用回复（秒）
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
    """协议返回「请求已不存在 / 已失效」等（用于提示文案）。"""
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


request_cmd = on_request(priority=14, block=False)

list_friends_cmd = on_command(
    LIST_FRIEND_COMMAND,
    aliases=set(LIST_FRIEND_ALIASES),
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.list_friends"),
)
approve_latest_cmd = on_command(
    APPROVE_LATEST_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.approve_latest"),
)
reject_latest_cmd = on_command(
    REJECT_LATEST_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.reject_latest"),
)
approve_friend_cmd = on_command(
    APPROVE_FRIEND_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.approve_friend"),
)
approve_all_friends_cmd = on_command(
    APPROVE_ALL_FRIENDS_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.approve_all_friends"),
)
reject_all_friends_cmd = on_command(
    REJECT_ALL_FRIENDS_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.reject_all_friends"),
)
list_groups_cmd = on_command(
    LIST_GROUP_COMMAND,
    aliases=set(LIST_GROUP_ALIASES),
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.list_groups"),
)
approve_group_cmd = on_command(
    APPROVE_GROUP_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.approve_group"),
)
approve_all_groups_cmd = on_command(
    APPROVE_ALL_GROUPS_COMMAND,
    aliases=set(APPROVE_ALL_GROUPS_ALIASES),
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.approve_all_groups"),
)
reject_all_groups_cmd = on_command(
    REJECT_ALL_GROUPS_COMMAND,
    aliases=set(REJECT_ALL_GROUPS_ALIASES),
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.reject_all_groups"),
)
reject_friend_cmd = on_command(
    REJECT_FRIEND_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.reject_friend"),
)
reject_group_cmd = on_command(
    REJECT_GROUP_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.reject_group"),
)
auto_accept_status_cmd = on_command(
    AUTO_ACCEPT_STATUS_COMMAND,
    aliases=set(AUTO_ACCEPT_STATUS_ALIASES),
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.auto_accept_status"),
)
enable_auto_friend_cmd = on_command(
    ENABLE_AUTO_FRIEND_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.enable_auto_friend"),
)
disable_auto_friend_cmd = on_command(
    DISABLE_AUTO_FRIEND_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.disable_auto_friend"),
)
enable_auto_group_cmd = on_command(
    ENABLE_AUTO_GROUP_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.enable_auto_group"),
)
disable_auto_group_cmd = on_command(
    DISABLE_AUTO_GROUP_COMMAND,
    priority=5,
    block=True,
    permission=private_message_permission_for_command("request.disable_auto_group"),
)


def plugin_config() -> Config:
    from .config import get_request_handler_config

    return get_request_handler_config()


async def notify_admins(bot: Bot, msg: str, *, kind: str, target_id: str) -> bool:
    bot_key = str(bot.self_id)
    admins = await get_bot_admins(int(bot.self_id))
    plugin_cfg = plugin_config()
    if not plugin_cfg.request_handler_notify_superusers:
        superusers = {int(uid) for uid in get_driver().config.superusers}
        # 过滤掉 SUPERUSER，若全部都是 SUPERUSER 则发送给SUPERUSER
        admins = [uid for uid in admins if uid not in superusers] or admins
    # Bot 未配置 admins 时仍通知 SUPERUSER，避免无人收件
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
        if await request_handler_plugin_disabled(bot_id=bot_id):
            continue
        try:
            doubts = await fetch_doubt_friends(bot)
        except Exception as e:
            logger.debug(f"bot [{bot_key}] poll doubt friends failed: {e}")
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
            msg = f"[好友申请]\n申请人：{nickname}（{uid}）\n{REQUEST_HANDLER_HELP_HINT}"
            if await notify_admins(bot, msg, kind="friend", target_id=uid):
                set_last_notified(bot_key, "friend", uid)
                notified_set.add(uid)
                state_updated = True
            else:
                logger.warning(f"bot [{bot_key}] doubt friends notify_admins failed uid={uid}")

        notified_map[bot_key] = notified_set

    if state_updated:
        save_doubt_poll_state(primed_bots, notified_map)


async def approval_reply_rule(bot: Bot, event: Event) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False
    has_perm = False
    for perm_id in ("request.approval_reply", "request.reject_friend", "request.reject_group"):
        if await satisfies_command_permission(bot, event, perm_id):
            has_perm = True
            break
    if not has_perm:
        return False
    if not event.reply:
        return False
    quoted_body = None
    if event.reply.message is not None:
        quoted_body = event.reply.message.extract_plain_text()
    bot_key = str(bot.self_id)
    mid = str(event.reply.message_id)
    bot_msgs = approval_notice_map.get(bot_key)
    if bot_msgs and mid in bot_msgs:
        meta = bot_msgs[mid]
        ts = float(meta.get("ts") or 0)
        if ts and notify_ts_expired(ts):
            bot_msgs.pop(mid, None)
            if not bot_msgs:
                approval_notice_map.pop(bot_key, None)
            persist_approval_notice_map(bot_key)
            return False
        return True
    return parse_approval_notice_meta(quoted_body) is not None


approval_reply_cmd = on_message(rule=Rule(approval_reply_rule), priority=4, block=True)


@approval_reply_cmd.handle()
async def handle_approval_reply(bot: Bot, event: PrivateMessageEvent):
    bot_key = str(bot.self_id)
    mid = str(event.reply.message_id)
    quoted_body = None
    if event.reply and event.reply.message is not None:
        quoted_body = event.reply.message.extract_plain_text()
    meta = approval_notice_map.get(bot_key, {}).get(mid)
    if not meta:
        meta = parse_approval_notice_meta(quoted_body)
    if not meta:
        return
    text = extract_approval_reply_text_from_body(event.get_plaintext() or "", quoted_body)
    action = classify_approval_reply_text(text)
    if action is None:
        await approval_reply_cmd.finish("引用审批消息后，正文须为：同意 / 好 / 留空，或 拒绝 / 不要 / 否。")
    kind = str(meta["kind"])
    target_id = str(meta["target_id"])
    if action == "approve":
        if not await satisfies_command_permission(bot, event, "request.approval_reply"):
            await approval_reply_cmd.finish("你没有引用同意的权限。")
        if kind == "friend":
            ok, msg = await approve_friend_by_uid(bot, bot_key, target_id)
        else:
            ok, msg = await approve_group_invite_by_gid(bot, bot_key, target_id)
    else:
        reject_perm = "request.reject_friend" if kind == "friend" else "request.reject_group"
        if not await satisfies_command_permission(bot, event, reject_perm):
            await approval_reply_cmd.finish("你没有引用拒绝的权限。")
        if kind == "friend":
            ok, msg = await reject_friend_by_uid(bot, bot_key, target_id)
        else:
            ok, msg = await reject_group_invite_by_gid(bot, bot_key, target_id)
    if ok:
        clear_quick_approve_state(bot_key, kind, target_id)
    await approval_reply_cmd.finish(msg)


@request_cmd.handle()
async def handle_friend_request(bot: Bot, event: FriendRequestEvent):
    bot_id = int(bot.self_id)
    bot_key = str(bot_id)
    pending_friend.setdefault(bot_key, {})[str(event.user_id)] = event.flag
    persist_pending_friend(bot_key)

    bot_config = BotConfig(bot_id)
    if await bot_config.auto_accept_friend():
        await event.approve(bot)
        pending_friend.get(bot_key, {}).pop(str(event.user_id), None)
        persist_pending_friend(bot_key)
        return

    if not await request_handler_plugin_disabled(bot_id=bot_id):
        nickname = await get_nickname(bot, event.user_id)
        msg = (
            f"[好友申请]\n申请人：{nickname}（{event.user_id}）\n"
            f"验证：{event.comment or '-'}\n{REQUEST_HANDLER_HELP_HINT}"
        )
        if await notify_admins(bot, msg, kind="friend", target_id=str(event.user_id)):
            set_last_notified(bot_key, "friend", str(event.user_id))


@list_friends_cmd.handle()
async def handle_list_friends(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.list_friends"):
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
        lines.append(f"  {nickname}（{uid}）")
    lines.append(build_list_tail("friend"))
    await list_friends_cmd.finish("\n".join(lines))


@approve_latest_cmd.handle()
async def handle_approve_latest(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.approve_latest"):
        return
    arg = args.extract_plain_text().strip()
    if arg:
        await approve_latest_cmd.finish(build_quick_action_arg_hint(APPROVE_LATEST_COMMAND))
    bot_key = str(bot.self_id)
    entry = get_last_notified(bot_key)
    if not entry:
        await approve_latest_cmd.finish(build_quick_action_missing_hint(APPROVE_LATEST_COMMAND))
    kind, target_id, _ts = entry
    if kind == "friend":
        ok, msg = await approve_friend_by_uid(bot, bot_key, target_id)
    else:
        ok, msg = await approve_group_invite_by_gid(bot, bot_key, target_id)
    if ok:
        clear_quick_approve_state(bot_key, kind, target_id)
    await approve_latest_cmd.finish(msg)


@reject_latest_cmd.handle()
async def handle_reject_latest(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.reject_latest"):
        return
    arg = args.extract_plain_text().strip()
    if arg:
        await reject_latest_cmd.finish(build_quick_action_arg_hint(REJECT_LATEST_COMMAND))
    bot_key = str(bot.self_id)
    entry = get_last_notified(bot_key)
    if not entry:
        await reject_latest_cmd.finish(build_quick_action_missing_hint(REJECT_LATEST_COMMAND))
    kind, target_id, _ts = entry
    if kind == "friend":
        ok, msg = await reject_friend_by_uid(bot, bot_key, target_id)
    else:
        ok, msg = await reject_group_invite_by_gid(bot, bot_key, target_id)
    if ok:
        clear_quick_approve_state(bot_key, kind, target_id)
    await reject_latest_cmd.finish(msg)


@approve_friend_cmd.handle()
async def handle_approve_friend(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.approve_friend"):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await approve_friend_cmd.finish(f"格式：{APPROVE_FRIEND_COMMAND} <QQ号>")

    bot_key = str(bot.self_id)
    ok, msg = await approve_friend_by_uid(bot, bot_key, arg)
    if ok:
        clear_quick_approve_state(bot_key, "friend", arg)
    await approve_friend_cmd.finish(msg)


@reject_friend_cmd.handle()
async def handle_reject_friend(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.reject_friend"):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await reject_friend_cmd.finish(f"格式：{REJECT_FRIEND_COMMAND} <QQ号>")

    bot_key = str(bot.self_id)
    ok, msg = await reject_friend_by_uid(bot, bot_key, arg)
    if ok:
        clear_quick_approve_state(bot_key, "friend", arg)
    await reject_friend_cmd.finish(msg)


@list_groups_cmd.handle()
async def handle_list_groups(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.list_groups"):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_group.get(bot_key, {})
    if not bot_pending:
        await list_groups_cmd.finish("暂无待处理入群申请")
    lines = [f"待处理入群申请（共 {len(bot_pending)} 条）："]
    for group_key, req in bot_pending.items():
        nickname = await get_nickname(bot, req["user_id"])
        group_name = await get_group_name(bot, int(group_key))
        lines.append(f"  {group_name}（{group_key}）← {nickname}（{req['user_id']}）邀请")
    lines.append(build_list_tail("group"))
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
        persist_pending_group(bot_key)

        bot_config = BotConfig(bot_id)
        if await bot_config.auto_accept_group() or await user_is_bot_admin(bot_id, event.user_id):
            await event.approve(bot)
            pending_group.get(bot_key, {}).pop(group_key, None)
            persist_pending_group(bot_key)
            return

        if not await request_handler_plugin_disabled(bot_id=bot_id):
            nickname = await get_nickname(bot, event.user_id)
            group_name = await get_group_name(bot, event.group_id)
            msg = (
                f"[入群邀请]\n"
                f"邀请人：{nickname}（{event.user_id}）\n"
                f"群：{group_name}（{event.group_id}）\n"
                f"{REQUEST_HANDLER_HELP_HINT}"
            )
            if await notify_admins(bot, msg, kind="group", target_id=group_key):
                set_last_notified(bot_key, "group", group_key)


@approve_all_friends_cmd.handle()
async def handle_approve_all_friends(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.approve_all_friends"):
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
        except ActionFailed:
            fail += 1
            failure_cleanup_friend(bot_key, uid)
            cleared_friend_ids.add(uid)
        except Exception:
            fail += 1
    persist_pending_friend(bot_key)

    for uid, flag in list(doubt_requests.items()):
        try:
            await bot.call_api("set_doubt_friends_add_request", flag=flag, approve=True)
            cached_doubt_friend[bot_key].pop(uid, None)
            ok += 1
            cleared_friend_ids.add(uid)
        except ActionFailed:
            fail += 1
            failure_cleanup_friend(bot_key, uid)
            cleared_friend_ids.add(uid)
        except Exception:
            fail += 1

    for uid in cleared_friend_ids:
        clear_quick_approve_state(bot_key, "friend", uid)

    await approve_all_friends_cmd.finish(f"已同意 {ok} 条好友申请" + (f"，{fail} 条失败" if fail else ""))


@reject_all_friends_cmd.handle()
async def handle_reject_all_friends(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.reject_all_friends"):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_friend.get(bot_key, {})
    doubt_requests = await fetch_doubt_friends(bot)
    cached_doubt_friend[bot_key] = doubt_requests

    if not bot_pending and not doubt_requests:
        await reject_all_friends_cmd.finish("暂无待处理好友申请")

    ok, fail = 0, 0
    cleared_friend_ids: set[str] = set()
    for uid, flag in list(bot_pending.items()):
        try:
            await bot.set_friend_add_request(flag=flag, approve=False)
            bot_pending.pop(uid, None)
            ok += 1
            cleared_friend_ids.add(uid)
        except ActionFailed:
            fail += 1
            failure_cleanup_friend(bot_key, uid)
            cleared_friend_ids.add(uid)
        except Exception:
            fail += 1
    persist_pending_friend(bot_key)

    for uid, flag in list(doubt_requests.items()):
        try:
            await bot.call_api("set_doubt_friends_add_request", flag=flag, approve=False)
            cached_doubt_friend[bot_key].pop(uid, None)
            ok += 1
            cleared_friend_ids.add(uid)
        except ActionFailed:
            fail += 1
            failure_cleanup_friend(bot_key, uid)
            cleared_friend_ids.add(uid)
        except Exception:
            fail += 1

    for uid in cleared_friend_ids:
        clear_quick_approve_state(bot_key, "friend", uid)

    await reject_all_friends_cmd.finish(f"已拒绝 {ok} 条好友申请" + (f"，{fail} 条失败" if fail else ""))


@approve_all_groups_cmd.handle()
async def handle_approve_all_groups(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.approve_all_groups"):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_group.get(bot_key, {})
    if not bot_pending:
        await approve_all_groups_cmd.finish("暂无待处理入群申请")
    ok, fail = 0, 0
    cleared_group_keys: set[str] = set()
    for key, req in list(bot_pending.items()):
        try:
            await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=True)
            bot_pending.pop(key, None)
            ok += 1
            cleared_group_keys.add(key)
        except ActionFailed:
            fail += 1
            failure_cleanup_group(bot_key, key)
            cleared_group_keys.add(key)
        except Exception:
            fail += 1
    persist_pending_group(bot_key)
    for gkey in cleared_group_keys:
        clear_quick_approve_state(bot_key, "group", gkey)
    await approve_all_groups_cmd.finish(f"已同意 {ok} 条入群申请" + (f"，{fail} 条失败" if fail else ""))


@reject_all_groups_cmd.handle()
async def handle_reject_all_groups(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.reject_all_groups"):
        return
    bot_key = str(bot.self_id)
    bot_pending = pending_group.get(bot_key, {})
    if not bot_pending:
        await reject_all_groups_cmd.finish("暂无待处理入群申请")
    ok, fail = 0, 0
    cleared_group_keys: set[str] = set()
    for key, req in list(bot_pending.items()):
        try:
            await bot.set_group_add_request(flag=req["flag"], sub_type="invite", approve=False)
            bot_pending.pop(key, None)
            ok += 1
            cleared_group_keys.add(key)
        except ActionFailed:
            fail += 1
            failure_cleanup_group(bot_key, key)
            cleared_group_keys.add(key)
        except Exception:
            fail += 1
    persist_pending_group(bot_key)
    for gkey in cleared_group_keys:
        clear_quick_approve_state(bot_key, "group", gkey)
    await reject_all_groups_cmd.finish(f"已拒绝 {ok} 条入群申请" + (f"，{fail} 条失败" if fail else ""))


@approve_group_cmd.handle()
async def handle_approve_group(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.approve_group"):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await approve_group_cmd.finish(f"格式：{APPROVE_GROUP_COMMAND} <群号>")

    bot_key = str(bot.self_id)
    group_key = str(int(arg))
    ok, msg = await approve_group_invite_by_gid(bot, bot_key, group_key)
    if ok:
        clear_quick_approve_state(bot_key, "group", group_key)
    await approve_group_cmd.finish(msg)


@auto_accept_status_cmd.handle()
async def handle_auto_accept_status(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.auto_accept_status"):
        return
    bot_config = BotConfig(int(bot.self_id))
    friend_on = await bot_config.auto_accept_friend()
    group_on = await bot_config.auto_accept_group()
    friend_str = "✅ 开启" if friend_on else "❌ 关闭"
    group_str = "✅ 开启" if group_on else "❌ 关闭"
    await auto_accept_status_cmd.finish(
        f"好友自动同意：{friend_str}\n入群自动同意：{group_str}\n"
        f"切换：{ENABLE_AUTO_FRIEND_COMMAND} / {DISABLE_AUTO_FRIEND_COMMAND}；"
        f"{ENABLE_AUTO_GROUP_COMMAND} / {DISABLE_AUTO_GROUP_COMMAND}"
    )


@enable_auto_friend_cmd.handle()
async def handle_enable_auto_friend(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.enable_auto_friend"):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_friend(True)
    await enable_auto_friend_cmd.finish("已开启好友自动同意")


@disable_auto_friend_cmd.handle()
async def handle_disable_auto_friend(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.disable_auto_friend"):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_friend(False)
    await disable_auto_friend_cmd.finish("已关闭好友自动同意")


@enable_auto_group_cmd.handle()
async def handle_enable_auto_group(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.enable_auto_group"):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_group(True)
    await enable_auto_group_cmd.finish("已开启入群自动同意")


@disable_auto_group_cmd.handle()
async def handle_disable_auto_group(bot: Bot, event: MessageEvent):
    if not await satisfies_command_permission(bot, event, "request.disable_auto_group"):
        return
    await BotConfig(int(bot.self_id)).set_auto_accept_group(False)
    await disable_auto_group_cmd.finish("已关闭入群自动同意")


@reject_group_cmd.handle()
async def handle_reject_group(bot: Bot, event: MessageEvent, args: Message = CommandArg()):  # noqa: B008
    if not await satisfies_command_permission(bot, event, "request.reject_group"):
        return
    arg = args.extract_plain_text().strip()
    if not arg.isdigit():
        await reject_group_cmd.finish(f"格式：{REJECT_GROUP_COMMAND} <群号>")

    bot_key = str(bot.self_id)
    group_key = str(int(arg))
    ok, msg = await reject_group_invite_by_gid(bot, bot_key, group_key)
    if ok:
        clear_quick_approve_state(bot_key, "group", group_key)
    await reject_group_cmd.finish(msg)
