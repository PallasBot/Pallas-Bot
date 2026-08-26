"""Pallas-Bot WebUI console API: friend/group list and requests."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from nonebot import get_bots, logger
from pydantic import BaseModel, ConfigDict, Field

from .console_read_cache import cached_read, drop_read_cache
from .extended_common import (
    CONSOLE_APPROVAL_RELATED_CACHE_PREFIXES,
    check_pallas_write_token,
    shard_hub_console,
)

if TYPE_CHECKING:
    from .config import Config


def _bot_adapter_label(bot: object) -> str:
    try:
        a = getattr(bot, "adapter", None)
        if a is not None and hasattr(a, "get_name"):
            return str(a.get_name())
    except Exception:  # noqa: BLE001
        pass
    return ""


def _is_onebot_v11_bot(bot: object) -> bool:
    try:
        from nonebot.adapters.onebot.v11 import Bot as V11Bot  # type: ignore[attr-defined]

        return isinstance(bot, V11Bot)
    except Exception:  # noqa: BLE001
        return False


def _read_pending_friend_requests_disk() -> dict[str, dict[str, str]]:
    """与 request_handler 插件写入的 JSON 结构一致：{ bot_id: { user_id: flag } }。"""

    from pallas.core.foundation.paths import plugin_data_dir

    path = plugin_data_dir("request_handler", create=False) / "pending_friend_requests.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for bot_key, mp in raw.items():
        if not isinstance(mp, dict):
            continue
        bk = str(bot_key)
        out[bk] = {str(u): str(f) for u, f in mp.items()}
    return out


def _save_pending_friend_requests_disk(data: dict[str, dict[str, str]]) -> None:
    from pallas.core.foundation.paths import plugin_data_dir

    path = plugin_data_dir("request_handler") / "pending_friend_requests.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_pending_group_requests_disk() -> dict[str, dict[str, dict[str, Any]]]:
    """与 request_handler 插件写入的 JSON 结构一致：{ bot_id: { group_id: request } }。"""

    from pallas.core.foundation.paths import plugin_data_dir

    path = plugin_data_dir("request_handler", create=False) / "pending_group_requests.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for bot_key, mp in raw.items():
        if not isinstance(mp, dict):
            continue
        clean: dict[str, dict[str, Any]] = {}
        for req in mp.values():
            if not isinstance(req, dict):
                continue
            group_id = req.get("group_id")
            user_id = req.get("user_id")
            flag = req.get("flag")
            if flag is None:
                continue
            try:
                group_i = int(group_id)
                user_i = int(user_id)
            except (TypeError, ValueError):
                continue
            clean[str(group_i)] = {
                "flag": str(flag),
                "sub_type": str(req.get("sub_type") or "invite"),
                "user_id": user_i,
                "group_id": group_i,
                "comment": str(req.get("comment") or ""),
            }
        out[str(bot_key)] = clean
    return out


def _save_pending_group_requests_disk(data: dict[str, dict[str, dict[str, Any]]]) -> None:
    from pallas.core.foundation.paths import plugin_data_dir

    path = plugin_data_dir("request_handler") / "pending_group_requests.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_online_onebot_v11_bot(self_id: str) -> tuple[str, object]:
    target = str(self_id).strip()
    for key, bot in get_bots().items():
        if str(getattr(bot, "self_id", "") or "") != target:
            continue
        if not _is_onebot_v11_bot(bot):
            raise HTTPException(status_code=400, detail="当前连接不是 OneBot V11")
        return str(key), bot
    raise HTTPException(status_code=404, detail="指定账号当前未连接")


def _console_bot_online_in_cluster(self_id: str) -> bool:

    if not shard_hub_console():
        return False
    target = str(self_id).strip()
    if not target.isdigit():
        return False
    from pallas.core.platform.shard.presence import get_cluster_online_bot_ids

    return int(target) in get_cluster_online_bot_ids()


def _console_bot_connection_meta(self_id: int) -> tuple[str, str]:
    """分片 hub：无本地 Bot 时从 presence 取 connection_key / adapter。"""
    target = str(int(self_id))
    for key, bot in get_bots().items():
        if str(getattr(bot, "self_id", "") or "") == target:
            if not _is_onebot_v11_bot(bot):
                raise HTTPException(status_code=400, detail="当前连接不是 OneBot V11")
            return str(key), _bot_adapter_label(bot)
    if _console_bot_online_in_cluster(target):
        from pallas.core.platform.shard.presence import read_presence_bots

        rec = read_presence_bots().get(target, {})
        return (
            str(rec.get("connection_key") or target),
            str(rec.get("adapter") or ""),
        )
    raise HTTPException(status_code=404, detail="指定账号当前未连接")


async def _onebot_v11_api_call(self_id: int, api: str, **params: Any) -> Any:
    target = str(int(self_id))
    for bot in get_bots().values():
        if str(getattr(bot, "self_id", "") or "") != target:
            continue
        if not _is_onebot_v11_bot(bot):
            raise HTTPException(status_code=400, detail="当前连接不是 OneBot V11，无法调用协议接口")
        try:
            return await bot.call_api(api, **params)  # type: ignore[union-attr]
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(e)) from e
    if _console_bot_online_in_cluster(target):
        from pallas.core.platform.shard.coord.bot_action import call_onebot_api_as_bot

        ok, result = await call_onebot_api_as_bot(
            int(self_id),
            api,
            dict(params),
            timeout_sec=60.0,
        )
        if not ok:
            raise HTTPException(status_code=502, detail=f"无法在 worker 上执行 {api}")
        return result
    raise HTTPException(status_code=404, detail="指定账号当前未连接")


def _normalize_group_list_item(item: object) -> dict[str, Any] | None:
    if hasattr(item, "model_dump"):
        try:
            item = item.model_dump()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    elif hasattr(item, "dict") and callable(item.dict):
        try:
            item = item.dict()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    if not isinstance(item, dict):
        return None
    gid = item.get("group_id")
    try:
        group_id = int(gid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if group_id <= 0:
        return None
    try:
        member_count = int(float(item.get("member_count") or 0))
    except (TypeError, ValueError):
        member_count = 0
    try:
        max_member_count = int(float(item.get("max_member_count") or 0))
    except (TypeError, ValueError):
        max_member_count = 0
    return {
        "group_id": group_id,
        "group_name": str(item.get("group_name") or ""),
        "member_count": member_count,
        "max_member_count": max_member_count,
    }


def _normalize_friend_list_item(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    uid = item.get("user_id")
    try:
        user_id = int(uid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if user_id <= 0:
        return None
    sex = item.get("sex")
    return {
        "user_id": user_id,
        "nickname": str(item.get("nickname") or ""),
        "remark": str(item.get("remark") or ""),
        **({"sex": sex} if sex is not None else {}),
    }


def _parse_group_list_raw(
    raw: object,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    groups_raw: list[Any]
    if isinstance(raw, list):
        groups_raw = raw
    elif isinstance(raw, dict):
        groups_raw = []
        for k in ("group_list", "groups", "data"):
            v = raw.get(k)
            if isinstance(v, list):
                groups_raw = v
                break
        if not groups_raw:
            logger.warning(
                "[WebUI] get_group_list returned a dict without a list field; keys were [{}]", list(raw.keys())
            )
    else:
        logger.warning("[WebUI] get_group_list 返回意外类型 {}", type(raw).__name__)
        groups_raw = []
    out: list[dict[str, Any]] = []
    for it in groups_raw:
        try:
            row = _normalize_group_list_item(it)
        except Exception as e:  # noqa: BLE001
            logger.warning("[WebUI] Failed to parse group list item [{}]: [{}]", repr(it), e)
            continue
        if row:
            out.append(row)
    out.sort(key=lambda r: int(r["group_id"]))
    truncated = len(out) > limit
    if truncated:
        out = out[:limit]
    return out, None, truncated


def _parse_friend_list_raw(
    raw: object,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    friends_raw: list[Any]
    if isinstance(raw, list):
        friends_raw = raw
    elif isinstance(raw, dict):
        friends_raw = []
        for k in ("friend_list", "friends", "data"):
            v = raw.get(k)
            if isinstance(v, list):
                friends_raw = v
                break
    else:
        friends_raw = []
    out: list[dict[str, Any]] = []
    for it in friends_raw:
        row = _normalize_friend_list_item(it)
        if row:
            out.append(row)
    out.sort(key=lambda r: int(r["user_id"]))
    truncated = len(out) > limit
    if truncated:
        out = out[:limit]
    return out, None, truncated


async def _call_get_group_list(
    bot: object,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """OneBot V11 `get_group_list`；不同实现可能返回 list 或包在 dict 里。

    返回 (groups, error, truncated)。
    """
    try:
        raw = await bot.call_api("get_group_list")  # type: ignore[union-attr]
    except Exception as e:  # noqa: BLE001
        logger.warning("[WebUI] get_group_list 调用失败: {}", e)
        return [], str(e), False
    return _parse_group_list_raw(raw, limit=limit)


async def _call_get_friend_list(
    bot: object,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """OneBot V11 `get_friend_list`；不同实现可能返回 list 或包在 dict 里。

    返回 (friends, error, truncated)。
    """
    try:
        raw = await bot.call_api("get_friend_list")  # type: ignore[union-attr]
    except Exception as e:  # noqa: BLE001
        return [], str(e), False
    return _parse_friend_list_raw(raw, limit=limit)


async def _fetch_group_list_for_self_id(
    self_id: int,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    try:
        raw = await _onebot_v11_api_call(int(self_id), "get_group_list")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("[WebUI] get_group_list failed for bot [{}]: [{}]", self_id, e)
        return [], str(e), False
    return _parse_group_list_raw(raw, limit=limit)


async def _fetch_friend_list_for_self_id(
    self_id: int,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    try:
        raw = await _onebot_v11_api_call(int(self_id), "get_friend_list")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        return [], str(e), False
    return _parse_friend_list_raw(raw, limit=limit)


async def _get_doubt_friends_for_self_id(self_id: int) -> list[dict[str, Any]]:
    try:
        raw = await _onebot_v11_api_call(int(self_id), "get_doubt_friends_add_request", count=50)
    except HTTPException as e:
        logger.debug(
            "[WebUI] get_doubt_friends_add_request is unavailable for bot [{}]: [{}]",
            self_id,
            getattr(e, "detail", e),
        )
        return []
    except Exception as e:  # noqa: BLE001
        logger.debug("[WebUI] get_doubt_friends_add_request failed for bot [{}]: [{}]", self_id, e)
        return []
    rows = _rows_from_doubt_friends_api(raw)
    for row in rows:
        if not str(row.get("flag") or "").strip():
            uid = row.get("uid")
            if uid is not None and str(uid).strip():
                row["flag"] = str(uid).strip()
    return rows


async def _stranger_nickname_for_self_id(self_id: int, user_id: int) -> str:
    try:
        raw = await _onebot_v11_api_call(int(self_id), "get_stranger_info", user_id=int(user_id))
    except Exception:  # noqa: BLE001
        return ""
    if not isinstance(raw, dict):
        return ""
    return _nickname_from_stranger_info(raw)


async def _enrich_friend_request_rows_nicknames_for_self_id(
    self_id: int,
    pending: list[dict[str, Any]],
    doubt: list[dict[str, Any]],
) -> None:
    need: set[int] = set()
    for p in pending:
        if str(p.get("nickname", "")).strip():
            continue
        uid = p.get("user_id")
        if uid is None:
            continue
        try:
            need.add(int(uid))
        except (TypeError, ValueError):
            pass
    for d in doubt:
        if str(d.get("nickname", "")).strip():
            continue
        uid = d.get("user_id")
        if uid is None:
            continue
        try:
            need.add(int(uid))
        except (TypeError, ValueError):
            pass
    nick_map: dict[int, str] = {}
    for uid in sorted(need):
        nick = await _stranger_nickname_for_self_id(self_id, uid)
        if nick:
            nick_map[uid] = nick
    for p in pending:
        try:
            uid = int(p["user_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if not str(p.get("nickname", "")).strip() and uid in nick_map:
            p["nickname"] = nick_map[uid]
    for d in doubt:
        try:
            uid = int(d["user_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if not str(d.get("nickname", "")).strip() and uid in nick_map:
            d["nickname"] = nick_map[uid]


async def _console_set_friend_add_request(self_id: int, *, flag: str, approve: bool) -> None:
    await _onebot_v11_api_call(
        int(self_id),
        "set_friend_add_request",
        flag=str(flag),
        approve=bool(approve),
    )


async def _console_set_group_add_request(
    self_id: int,
    *,
    flag: str,
    sub_type: str,
    approve: bool,
) -> None:
    await _onebot_v11_api_call(
        int(self_id),
        "set_group_add_request",
        flag=str(flag),
        sub_type=str(sub_type or "invite"),
        approve=bool(approve),
    )


async def _console_set_doubt_friend_add_request(self_id: int, *, flag: str, approve: bool) -> None:
    await _onebot_v11_api_call(
        int(self_id),
        "set_doubt_friends_add_request",
        flag=str(flag),
        approve=bool(approve),
    )


def _rows_from_doubt_friends_api(raw: object) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    return []


async def _call_get_doubt_friends(bot: object) -> list[dict[str, Any]]:
    try:
        raw = await bot.call_api("get_doubt_friends_add_request", count=50)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return []
    rows = _rows_from_doubt_friends_api(raw)
    out: list[dict[str, Any]] = []
    for x in rows:
        uid_raw = x.get("user_id")
        if uid_raw is None:
            uid_raw = x.get("uin")
        if uid_raw is None:
            continue
        try:
            uid = int(uid_raw)
        except (TypeError, ValueError):
            continue
        flag = x.get("flag")
        if flag is None:
            flag = x.get("uid")
        if flag is None:
            continue
        flag_str = str(flag).strip()
        if not flag_str:
            continue
        row: dict[str, Any] = {"user_id": uid, "flag": flag_str}
        nick_raw = x.get("nickname") or x.get("nick") or x.get("name")
        if isinstance(nick_raw, str) and nick_raw.strip():
            row["nickname"] = nick_raw.strip()
        out.append(row)
    return out


async def _call_get_stranger_info_raw(bot: object, user_id: int) -> dict[str, Any] | None:
    try:
        raw = await bot.call_api("get_stranger_info", user_id=user_id)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return None
    return raw if isinstance(raw, dict) else None


def _nickname_from_stranger_info(raw: dict[str, Any]) -> str:
    nick = raw.get("nickname")
    if isinstance(nick, str) and nick.strip():
        return nick.strip()
    data = raw.get("data")
    if isinstance(data, dict):
        nick2 = data.get("nickname")
        if isinstance(nick2, str) and nick2.strip():
            return nick2.strip()
    return ""


async def _enrich_friend_request_rows_nicknames(
    bot: object,
    pending: list[dict[str, Any]],
    doubt: list[dict[str, Any]],
) -> None:
    if not _is_onebot_v11_bot(bot):
        return
    sid = str(getattr(bot, "self_id", "") or "").strip()
    if sid.isdigit():
        await _enrich_friend_request_rows_nicknames_for_self_id(int(sid), pending, doubt)
        return
    need: set[int] = set()
    for p in pending:
        if str(p.get("nickname", "")).strip():
            continue
        uid = p.get("user_id")
        if uid is None:
            continue
        try:
            need.add(int(uid))
        except (TypeError, ValueError):
            pass
    for d in doubt:
        if str(d.get("nickname", "")).strip():
            continue
        uid = d.get("user_id")
        if uid is None:
            continue
        try:
            need.add(int(uid))
        except (TypeError, ValueError):
            pass
    nick_map: dict[int, str] = {}
    for uid in sorted(need):
        raw = await _call_get_stranger_info_raw(bot, uid)
        if raw is None:
            continue
        nick = _nickname_from_stranger_info(raw)
        if nick:
            nick_map[uid] = nick
    for p in pending:
        try:
            uid = int(p["user_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if str(p.get("nickname", "")).strip():
            continue
        if uid in nick_map:
            p["nickname"] = nick_map[uid]
    for d in doubt:
        try:
            uid = int(d["user_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if str(d.get("nickname", "")).strip():
            continue
        if uid in nick_map:
            d["nickname"] = nick_map[uid]


def _normalize_message_item(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    out: dict[str, Any] = {}
    for k in ("message_id", "time", "raw_message", "message_type"):
        v = item.get(k)
        if v is not None:
            out[k] = v
    sender = item.get("sender")
    if isinstance(sender, dict):
        nick = sender.get("nickname")
        if nick is not None:
            out["nickname"] = str(nick)
        uid = sender.get("user_id")
        if uid is not None:
            try:
                out["user_id"] = int(uid)
            except (TypeError, ValueError):
                pass
    uid2 = item.get("user_id")
    if "user_id" not in out and uid2 is not None:
        try:
            out["user_id"] = int(uid2)
        except (TypeError, ValueError):
            pass
    gid = item.get("group_id")
    if gid is not None:
        try:
            out["group_id"] = int(gid)
        except (TypeError, ValueError):
            pass
    if not out:
        return None
    return out


async def _call_get_message_history(
    bot: object,
    *,
    kind: Literal["friend", "group"],
    target_id: int,
    count: int,
) -> list[dict[str, Any]]:
    base_params: dict[str, Any] = {
        "count": int(count),
        "reverse_order": False,
        "disable_get_url": False,
        "parse_mult_msg": True,
        "quick_reply": False,
        "reverseOrder": False,
    }
    if kind == "friend":
        key = "user_id"
        api_name = "get_friend_msg_history"
    else:
        key = "group_id"
        api_name = "get_group_msg_history"
    target_num = int(target_id)
    tried: list[dict[str, Any]] = [
        {**base_params, key: target_num},
        {**base_params, key: str(target_num)},
        {"count": int(count), key: target_num},
        {"count": int(count), key: str(target_num)},
    ]
    last_err: Exception | None = None
    raw: Any = {}
    for params in tried:
        try:
            raw = await bot.call_api(api_name, **params)  # type: ignore[union-attr]
            last_err = None
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
    if last_err is not None:
        raise last_err
    messages_raw: list[Any] = []
    if isinstance(raw, dict):
        maybe = raw.get("messages")
        if isinstance(maybe, list):
            messages_raw = maybe
        elif isinstance(raw.get("data"), dict):
            inner = raw["data"].get("messages")
            if isinstance(inner, list):
                messages_raw = inner
    elif isinstance(raw, list):
        messages_raw = raw
    out: list[dict[str, Any]] = []
    for it in messages_raw:
        row = _normalize_message_item(it)
        if row:
            out.append(row)
    out.sort(key=lambda x: int(x.get("time") or 0))
    return out


def _merge_protocol_snap_display_names(out: dict[str, dict[str, Any]]) -> None:
    """用协议端 accounts 的 display_name 补全资料（含未连接账号）。"""
    from pallas.core.foundation.db.pallas_console_data import pallas_protocol_snapshot

    snap = pallas_protocol_snapshot()
    if not snap or not isinstance(snap.get("accounts"), list):
        return
    for acc in snap["accounts"]:
        if not isinstance(acc, dict):
            continue
        sid = str(acc.get("qq") or acc.get("id") or "").strip()
        if not sid.isdigit():
            continue
        disp = str(acc.get("display_name") or acc.get("nickname") or "").strip()
        if sid in out:
            if disp:
                out[sid]["nickname"] = disp
        elif disp:
            out[sid] = {
                "nickname": disp,
                "user_id": int(sid),
                "connection_key": sid,
                "adapter": "",
                "shard_id": None,
                "online": False,
            }


def _fill_bot_profile_nicknames_for_accounts(
    out: dict[str, dict[str, Any]],
    account_ids: list[int] | tuple[int, ...] | set[int],
) -> None:
    """为库内账号补全缺失昵称：presence / 协议 accounts.json。"""
    from pallas.product.persona.self_identity import resolve_cached_login_nickname

    for raw_acc in account_ids:
        try:
            acc = int(raw_acc)
        except (TypeError, ValueError):
            continue
        if acc <= 0:
            continue
        sid = str(acc)
        existing = out.get(sid)
        if existing is not None and str(existing.get("nickname") or "").strip():
            continue
        nick = resolve_cached_login_nickname(acc)
        if not nick:
            continue
        if existing is not None:
            existing["nickname"] = nick
        else:
            out[sid] = {
                "nickname": nick,
                "user_id": acc,
                "connection_key": sid,
                "adapter": "",
                "shard_id": None,
                "online": False,
            }


async def _collect_online_bot_profiles(
    *,
    ensure_accounts: list[int] | None = None,
) -> dict[str, dict[str, Any]]:
    """尽力读取 Bot 账号资料；在线优先 get_login_info，离线回退协议/presence。"""

    if shard_hub_console():
        from pallas.console.webui.protocol_accounts import protocol_account_display_names
        from pallas.core.platform.shard.presence import read_presence_bots

        names = protocol_account_display_names()
        out: dict[str, dict[str, Any]] = {}
        for qq, rec in read_presence_bots().items():
            sid = str(rec.get("qq") or qq)
            nick = str(rec.get("nickname") or "").strip() or names.get(sid, "")
            out[sid] = {
                "nickname": nick,
                "user_id": int(sid) if sid.isdigit() else None,
                "connection_key": str(rec.get("connection_key") or sid),
                "adapter": str(rec.get("adapter") or ""),
                "shard_id": rec.get("shard_id"),
            }
        _merge_protocol_snap_display_names(out)
        if ensure_accounts:
            _fill_bot_profile_nicknames_for_accounts(out, ensure_accounts)
        return out

    from pallas.product.persona.self_identity import resolve_cached_login_nickname

    out = {}
    for key, bot in get_bots().items():
        self_id = str(getattr(bot, "self_id", "") or "").strip()
        if not self_id:
            continue
        if not _is_onebot_v11_bot(bot):
            continue
        try:
            raw = await bot.call_api("get_login_info")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            logger.debug("[WebUI] get_login_info failed for connection [{}] and bot [{}]", key, self_id)
            nick = resolve_cached_login_nickname(int(self_id)) if self_id.isdigit() else ""
            if nick:
                out[self_id] = {
                    "nickname": nick,
                    "user_id": int(self_id) if self_id.isdigit() else None,
                    "connection_key": str(key),
                    "adapter": _bot_adapter_label(bot),
                }
            continue
        if not isinstance(raw, dict):
            continue
        nickname = str(raw.get("nickname") or "").strip()
        if not nickname and self_id.isdigit():
            nickname = resolve_cached_login_nickname(int(self_id))
        user_id = raw.get("user_id")
        out[self_id] = {
            "nickname": nickname,
            "user_id": int(user_id) if isinstance(user_id, int) else None,
            "connection_key": str(key),
            "adapter": _bot_adapter_label(bot),
        }
    _merge_protocol_snap_display_names(out)
    if ensure_accounts:
        _fill_bot_profile_nicknames_for_accounts(out, ensure_accounts)
    return out


async def _doubt_friends_for_self_id_safe(self_id: int) -> list[dict[str, Any]]:
    try:
        return await _get_doubt_friends_for_self_id(self_id)
    except Exception as e:  # noqa: BLE001
        logger.debug("[WebUI] Failed to fetch doubtful friend requests for bot [{}]: [{}]", self_id, e)
        return []


async def _friend_requests_overview(
    *,
    self_id: str | None,
    include_doubt: bool,
) -> dict[str, Any]:
    disk = _read_pending_friend_requests_disk()
    online_by_self: dict[str, tuple[str, object]] = {}

    if shard_hub_console():
        from pallas.core.platform.shard.presence import read_presence_bots

        for key, rec in read_presence_bots().items():
            sid = str(rec.get("qq") or key)
            if sid:
                online_by_self[sid] = (str(rec.get("connection_key") or sid), None)
    else:
        for key, bot in get_bots().items():
            sid = str(getattr(bot, "self_id", "") or "")
            if sid:
                online_by_self[sid] = (str(key), bot)

    ids = set(disk.keys()) | set(online_by_self.keys())
    if self_id is not None and str(self_id).strip():
        want = str(self_id).strip()
        ids = {i for i in ids if i == want}

    def _sort_key(s: str) -> tuple[int, str]:
        return (int(s), s) if s.isdigit() else (10**18, s)

    sorted_ids = sorted(ids, key=_sort_key)
    doubt_by_sid: dict[str, list[dict[str, Any]]] = {}
    if include_doubt:
        doubt_targets = [sid for sid in sorted_ids if sid in online_by_self and sid.isdigit()]
        if doubt_targets:
            pairs = await asyncio.gather(
                *[_doubt_friends_for_self_id_safe(int(sid)) for sid in doubt_targets],
            )
            doubt_by_sid = dict(zip(doubt_targets, pairs, strict=True))

    rows: list[dict[str, Any]] = []
    for sid in sorted_ids:
        pend_map = disk.get(sid, {})
        pending = [{"user_id": int(u), "flag": fl} for u, fl in pend_map.items() if u.isdigit()]
        doubt: list[dict[str, Any]] = []
        conn: str | None = None
        adapter = ""
        online = sid in online_by_self
        if online:
            conn, bot = online_by_self[sid]
            if bot is not None:
                adapter = _bot_adapter_label(bot)
            elif sid.isdigit():
                _, adapter = _console_bot_connection_meta(int(sid))
            if sid.isdigit():
                sid_i = int(sid)
                if include_doubt:
                    doubt = list(doubt_by_sid.get(sid, []))
                if pending or doubt:
                    await _enrich_friend_request_rows_nicknames_for_self_id(sid_i, pending, doubt)
        rows.append({
            "self_id": sid,
            "connection_key": conn,
            "adapter": adapter,
            "online": online,
            "pending_friend_requests": pending,
            "doubt_friend_requests": doubt,
        })
    return {"bots": rows}


class _RequestActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_id: int = Field(ge=1)
    kind: Literal["friend", "group"]
    action: Literal["approve", "reject"] = "approve"
    source: Literal["pending", "doubt"] = "pending"
    user_id: int | None = Field(default=None, ge=1)
    group_id: int | None = Field(default=None, ge=1)


class _RequestBatchFriendRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_id: int = Field(ge=1)
    user_id: int = Field(ge=1)
    source: Literal["pending", "doubt"] = "pending"


class _RequestBatchGroupRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_id: int = Field(ge=1)
    user_id: int = Field(ge=1)
    group_id: int = Field(ge=1)


class _LlmModelSwitchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=200)
    pull: bool = True


class _LlmModelNumGpuBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    num_gpu: int = Field(ge=0, le=999)


class _LlmModelPricingRowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_in: float = Field(default=0.0, ge=0)
    price_out: float = Field(default=0.0, ge=0)
    cache_price_in: float = Field(default=0.0, ge=0)
    cache_price_out: float = Field(default=0.0, ge=0)


class _LlmProviderModelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(default="", max_length=128)
    name: str = Field(min_length=1, max_length=200)
    is_default: bool = False
    capabilities: list[str] = Field(default_factory=list)
    model_effort: str = ""
    pricing_rules: list[dict[str, Any]] = Field(default_factory=list)


class _LlmProviderRowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    kind: str = Field(default="remote")
    base_url: str = ""
    api_key: str = ""
    api_keys: list[str] = Field(default_factory=list)
    api_key_env: str = ""
    clear_api_keys: bool = False
    default_model: str = ""
    models: list[_LlmProviderModelBody] = Field(default_factory=list)
    enabled: bool = True
    task_models: dict[str, str] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    model_effort: str = ""
    request_method: str = "chat_completions"
    model_pricing: dict[str, _LlmModelPricingRowBody] = Field(default_factory=dict)


class _LlmProvidersRoutingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain_fallback: list[str] = Field(default_factory=list)
    tasks: dict[str, str] = Field(default_factory=dict)
    tier_backups: dict[str, str] = Field(default_factory=dict)
    tier_backup_models: dict[str, str] = Field(default_factory=dict)
    task_backups: dict[str, str] = Field(default_factory=dict)
    task_backup_models: dict[str, str] = Field(default_factory=dict)
    route_source: str = ""
    cost_currency: str = ""


class _LlmProvidersDocumentBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    providers: list[_LlmProviderRowBody] = Field(default_factory=list)
    routing: _LlmProvidersRoutingBody = Field(default_factory=_LlmProvidersRoutingBody)


class _LlmProviderModelsDiscoverBody(BaseModel):
    """Bot 直连发现模型：由控制台传入草稿凭证，不经 AI Runtime。"""

    model_config = ConfigDict(extra="forbid")

    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    kind: str = ""
    request_method: str = ""


class _LlmLocalRoutingModelsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simple: str = ""
    medium: str = ""
    complex: str = ""
    vision: str = ""


class _LlmLocalRoutingTaskModelsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_chat: str = ""
    drunk: str = ""


class _LlmLocalRoutingConfigBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_model: str = Field(default="", max_length=200)
    local_multi_model_enabled: bool = False
    moe_models: _LlmLocalRoutingModelsBody = Field(default_factory=_LlmLocalRoutingModelsBody)
    task_models: _LlmLocalRoutingTaskModelsBody = Field(default_factory=_LlmLocalRoutingTaskModelsBody)
    env_file: str = ""


class _RequestActionsBatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"] = "approve"
    friends: list[_RequestBatchFriendRow] = Field(default_factory=list, max_length=500)
    groups: list[_RequestBatchGroupRow] = Field(default_factory=list, max_length=500)


def register_social_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    router_pub: APIRouter | None = None,
) -> None:
    """Register console routes."""

    @router.get(f"{x}/friend-requests", include_in_schema=True)
    async def _friend_requests(
        self_id: int | None = Query(default=None, description="仅查看指定 Bot QQ；不传则返回全部"),
        doubt: bool = Query(default=True, description="是否对在线 OneBot V11 号尝试拉取被过滤的可疑好友申请"),
    ) -> JSONResponse:
        """只读：request_handler 落盘的待处理好友申请 +协议侧可疑申请。"""

        async def _load() -> dict[str, Any]:
            sid = str(int(self_id)) if self_id is not None else None
            return await _friend_requests_overview(self_id=sid, include_doubt=bool(doubt))

        try:
            data = await cached_read(
                key=f"friend_requests:{self_id}:{int(doubt)}",
                loader=_load,
                ttl_sec=1.0,
                stale_sec=12.0,
                swr=True,
                persist_snapshot=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 读取好友申请概览失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/friend-list", include_in_schema=True)
    async def _friend_list(
        self_id: int = Query(..., description="Bot QQ（须当前在消息框架已连接）"),
        limit: int = Query(default=800, ge=1, le=8000),
    ) -> JSONResponse:
        """只读：对在线 Bot 调用 OneBot `get_friend_list`。"""
        cache_key = f"friend_list:{int(self_id)}:{int(limit)}"

        async def _load() -> dict[str, Any]:
            target = str(int(self_id))
            conn_key, adapter = _console_bot_connection_meta(int(self_id))
            friends, err, truncated = await _fetch_friend_list_for_self_id(int(self_id), limit=int(limit))
            return {
                "self_id": target,
                "connection_key": conn_key,
                "adapter": adapter,
                "friends": friends,
                "truncated": truncated,
                "limit": int(limit),
                "error": err,
            }

        try:
            payload = await cached_read(
                key=cache_key, loader=_load, ttl_sec=2.5, stale_sec=25.0, swr=True, persist_snapshot=True
            )
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 拉取好友列表失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": payload})

    @router.get(f"{x}/group-list", include_in_schema=True)
    async def _group_list(
        self_id: int = Query(..., description="Bot QQ（须当前在消息框架已连接）"),
        limit: int = Query(default=1000, ge=1, le=10000),
    ) -> JSONResponse:
        """只读：对在线 Bot 调用 OneBot `get_group_list`。"""
        cache_key = f"group_list:{int(self_id)}:{int(limit)}"

        async def _load() -> dict[str, Any]:
            target = str(int(self_id))
            conn_key, adapter = _console_bot_connection_meta(int(self_id))
            groups, err, truncated = await _fetch_group_list_for_self_id(int(self_id), limit=int(limit))
            return {
                "self_id": target,
                "connection_key": conn_key,
                "adapter": adapter,
                "groups": groups,
                "truncated": truncated,
                "limit": int(limit),
                "error": err,
            }

        try:
            payload = await cached_read(
                key=cache_key, loader=_load, ttl_sec=2.5, stale_sec=25.0, swr=True, persist_snapshot=True
            )
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 拉取群列表失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": payload})

    @router.get(f"{x}/request-overview", include_in_schema=True)
    async def _request_overview(
        self_id: int | None = Query(default=None, ge=1, description="仅查看指定 Bot QQ；不传则返回全部"),
        doubt: bool = Query(default=True, description="是否对在线 OneBot V11 号尝试拉取被过滤的可疑好友申请"),
    ) -> JSONResponse:
        filter_sid = str(int(self_id)) if self_id is not None else None

        async def _load() -> dict[str, Any]:
            friend = await _friend_requests_overview(self_id=filter_sid, include_doubt=bool(doubt))
            group = _read_pending_group_requests_disk()
            by_self: dict[str, dict[str, Any]] = {}
            for row in friend.get("bots", []):
                row_sid = str(row.get("self_id") or "")
                if not row_sid:
                    continue
                by_self[row_sid] = {
                    "self_id": row_sid,
                    "online": bool(row.get("online")),
                    "adapter": str(row.get("adapter") or ""),
                    "connection_key": row.get("connection_key"),
                    "pending_friend_requests": row.get("pending_friend_requests") or [],
                    "doubt_friend_requests": row.get("doubt_friend_requests") or [],
                    "pending_group_requests": [],
                }
            for gsid_raw, mp in group.items():
                gsid = str(gsid_raw)
                if filter_sid is not None and gsid != filter_sid:
                    continue
                row = by_self.setdefault(
                    gsid,
                    {
                        "self_id": gsid,
                        "online": False,
                        "adapter": "",
                        "connection_key": None,
                        "pending_friend_requests": [],
                        "doubt_friend_requests": [],
                        "pending_group_requests": [],
                    },
                )
                vals = [v for v in mp.values() if isinstance(v, dict)]
                vals.sort(key=lambda v: int(v.get("group_id") or 0))
                row["pending_group_requests"] = vals
            rows = sorted(
                by_self.values(),
                key=lambda r: int(str(r["self_id"])) if str(r["self_id"]).isdigit() else 10**18,
            )
            return {"bots": rows}

        cache_key = f"request_overview:{self_id or 'all'}:{int(doubt)}"
        try:
            data = await cached_read(
                key=cache_key, loader=_load, ttl_sec=1.2, stale_sec=15.0, swr=True, persist_snapshot=True
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 读取审批总览失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/request-actions", include_in_schema=True)
    async def _request_actions(
        body: _RequestActionBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        sid_i = int(body.self_id)
        _console_bot_connection_meta(sid_i)
        approve = body.action == "approve"
        if body.kind == "friend":
            if body.user_id is None:
                raise HTTPException(status_code=400, detail="friend 请求需要 user_id")
            uid = str(int(body.user_id))
            if body.source == "doubt":
                doubt = await _get_doubt_friends_for_self_id(sid_i)
                flag = next((str(x.get("flag") or "") for x in doubt if str(x.get("user_id")) == uid), "")
                if not flag:
                    raise HTTPException(status_code=404, detail="未找到可疑好友申请")
                await _console_set_doubt_friend_add_request(sid_i, flag=flag, approve=approve)
                drop_read_cache(CONSOLE_APPROVAL_RELATED_CACHE_PREFIXES)
                return JSONResponse({"ok": True, "data": {"handled": True}})
            pending = _read_pending_friend_requests_disk()
            by_bot = pending.get(str(body.self_id), {})
            flag = str(by_bot.get(uid) or "")
            if not flag:
                raise HTTPException(status_code=404, detail="未找到待处理好友申请")
            await _console_set_friend_add_request(sid_i, flag=flag, approve=approve)
            by_bot.pop(uid, None)
            pending[str(body.self_id)] = by_bot
            _save_pending_friend_requests_disk(pending)
            drop_read_cache(CONSOLE_APPROVAL_RELATED_CACHE_PREFIXES)
            return JSONResponse({"ok": True, "data": {"handled": True}})

        if body.group_id is None:
            raise HTTPException(status_code=400, detail="group 请求需要 group_id")
        pending_g = _read_pending_group_requests_disk()
        by_bot_g = pending_g.get(str(body.self_id), {})
        req = by_bot_g.get(str(int(body.group_id)))
        if not isinstance(req, dict):
            raise HTTPException(status_code=404, detail="未找到待处理群邀请")
        await _console_set_group_add_request(
            sid_i,
            flag=str(req.get("flag") or ""),
            sub_type=str(req.get("sub_type") or "invite"),
            approve=approve,
        )
        by_bot_g.pop(str(int(body.group_id)), None)
        pending_g[str(body.self_id)] = by_bot_g
        _save_pending_group_requests_disk(pending_g)
        drop_read_cache(CONSOLE_APPROVAL_RELATED_CACHE_PREFIXES)
        return JSONResponse({"ok": True, "data": {"handled": True}})

    @router.post(f"{x}/request-actions/batch", include_in_schema=True)
    async def _request_actions_batch(
        body: _RequestActionsBatchBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        """批量处理好友/入群审批；单次写盘与缓存失效，减少控制台往返。"""
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if not body.friends and not body.groups:
            raise HTTPException(status_code=400, detail="friends 与 groups 不能均为空")

        approve = body.action == "approve"
        friends_ok = 0
        friends_fail = 0
        friends_errors: list[dict[str, Any]] = []
        groups_ok = 0
        groups_fail = 0
        groups_errors: list[dict[str, Any]] = []

        pending_friend: dict[str, dict[str, str]] = {}
        if body.friends:
            pending_friend = _read_pending_friend_requests_disk()

        friends_by_sid: dict[str, list[_RequestBatchFriendRow]] = defaultdict(list)
        for it in body.friends:
            friends_by_sid[str(int(it.self_id))].append(it)

        for sid_str, items in friends_by_sid.items():
            try:
                _console_bot_connection_meta(int(sid_str))
            except HTTPException as e:
                detail = e.detail
                msg = detail if isinstance(detail, str) else str(detail)
                for it in items:
                    friends_fail += 1
                    friends_errors.append({
                        "self_id": int(sid_str),
                        "user_id": it.user_id,
                        "source": it.source,
                        "error": msg,
                    })
                continue

            if sid_str not in pending_friend:
                pending_friend[sid_str] = {}
            bot_pending = pending_friend[sid_str]
            sid_i = int(sid_str)

            for it in items:
                uid = str(int(it.user_id))
                try:
                    if it.source == "doubt":
                        doubt_rows = await _get_doubt_friends_for_self_id(sid_i)
                        flag = ""
                        for row in doubt_rows:
                            if not isinstance(row, dict):
                                continue
                            if str(row.get("user_id") or "") != uid:
                                continue
                            flag = str(row.get("flag") or "")
                            break
                        if not flag:
                            raise ValueError("未找到可疑好友申请")
                        await _console_set_doubt_friend_add_request(sid_i, flag=flag, approve=approve)
                    else:
                        flag = str(bot_pending.get(uid) or "")
                        if not flag:
                            raise ValueError("未找到待处理好友申请")
                        await _console_set_friend_add_request(sid_i, flag=flag, approve=approve)
                        bot_pending.pop(uid, None)
                    friends_ok += 1
                except Exception as e:  # noqa: BLE001
                    friends_fail += 1
                    friends_errors.append({
                        "self_id": int(sid_str),
                        "user_id": it.user_id,
                        "source": it.source,
                        "error": str(e),
                    })

            pending_friend[sid_str] = bot_pending

        if body.friends:
            _save_pending_friend_requests_disk(pending_friend)

        pending_group: dict[str, dict[str, dict[str, Any]]] = {}
        if body.groups:
            pending_group = _read_pending_group_requests_disk()

        groups_by_sid: dict[str, list[_RequestBatchGroupRow]] = defaultdict(list)
        for it in body.groups:
            groups_by_sid[str(int(it.self_id))].append(it)

        for sid_str, items in groups_by_sid.items():
            try:
                _console_bot_connection_meta(int(sid_str))
            except HTTPException as e:
                detail = e.detail
                msg = detail if isinstance(detail, str) else str(detail)
                for it in items:
                    groups_fail += 1
                    groups_errors.append({
                        "self_id": int(sid_str),
                        "user_id": it.user_id,
                        "group_id": it.group_id,
                        "error": msg,
                    })
                continue

            if sid_str not in pending_group:
                pending_group[sid_str] = {}
            bot_grp = pending_group[sid_str]
            sid_i = int(sid_str)

            for it in items:
                gkey = str(int(it.group_id))
                try:
                    req = bot_grp.get(gkey)
                    if not isinstance(req, dict):
                        raise ValueError("未找到待处理群邀请")
                    await _console_set_group_add_request(
                        sid_i,
                        flag=str(req.get("flag") or ""),
                        sub_type=str(req.get("sub_type") or "invite"),
                        approve=approve,
                    )
                    bot_grp.pop(gkey, None)
                    groups_ok += 1
                except Exception as e:  # noqa: BLE001
                    groups_fail += 1
                    groups_errors.append({
                        "self_id": int(sid_str),
                        "user_id": it.user_id,
                        "group_id": it.group_id,
                        "error": str(e),
                    })

            pending_group[sid_str] = bot_grp

        if body.groups:
            _save_pending_group_requests_disk(pending_group)
        drop_read_cache(CONSOLE_APPROVAL_RELATED_CACHE_PREFIXES)

        return JSONResponse({
            "ok": True,
            "data": {
                "friends_ok": friends_ok,
                "friends_fail": friends_fail,
                "friends_errors": friends_errors,
                "groups_ok": groups_ok,
                "groups_fail": groups_fail,
                "groups_errors": groups_errors,
            },
        })
