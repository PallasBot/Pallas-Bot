"""Pallas-Bot 控制台 API 用的数据读取/概览，与具体 HTTP 层解耦。"""

from __future__ import annotations

import asyncio
from typing import Any

from src.foundation.db import get_db_backend

# 防止误扫全表拖垮进程；超出部分由 API 文档说明需用其它工具
_BOT_LIST_CAP = 10_000
_GROUP_LIST_CAP = 10_000
_USER_LIST_CAP = 10_000


def _jsonable_sing_progress(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return str(obj)


def bot_config_to_public(doc_or_row: Any) -> dict[str, Any]:
    """统一 Mongo Document 与 PG Row 的 JSON 形态。"""
    return {
        "account": int(doc_or_row.account),
        "admins": list(doc_or_row.admins or []),
        "auto_accept_friend": bool(getattr(doc_or_row, "auto_accept_friend", False)),
        "auto_accept_group": bool(getattr(doc_or_row, "auto_accept_group", False)),
        "security": bool(getattr(doc_or_row, "security", False)),
        "taken_name": dict(doc_or_row.taken_name or {}),
        "drunk": dict(doc_or_row.drunk or {}),
        "disabled_plugins": list(doc_or_row.disabled_plugins or []),
        "community_roster_show_qq": bool(getattr(doc_or_row, "community_roster_show_qq", True)),
    }


async def bot_community_roster_show_qq_by_accounts(account_ids: list[int]) -> dict[int, bool]:
    """批量读取牛牛是否允许在社区名册展示 QQ；未建配置行视为 True。"""
    ids = sorted({int(x) for x in account_ids if int(x) > 0})
    if not ids:
        return {}
    backend = (get_db_backend() or "").lower()
    if _is_pg_backend(backend):
        from sqlalchemy import select

        from src.foundation.db.repository_pg import BotConfigRow, get_session

        async with get_session(read_only=True) as session:
            result = await session.execute(
                select(BotConfigRow.account, BotConfigRow.community_roster_show_qq).where(BotConfigRow.account.in_(ids))
            )
            out = {int(a): True for a in ids}
            for account, show_qq in result.all():
                out[int(account)] = bool(show_qq)
            return out
    from beanie.operators import In

    from src.foundation.db.modules import BotConfigModule

    out = {int(a): True for a in ids}
    docs = await BotConfigModule.find(In(BotConfigModule.account, ids)).to_list()
    for doc in docs:
        out[int(doc.account)] = bool(getattr(doc, "community_roster_show_qq", True))
    return out


def group_config_to_public(doc_or_row: Any) -> dict[str, Any]:
    sp = getattr(doc_or_row, "sing_progress", None)
    bu = getattr(doc_or_row, "blocked_user_ids", None) or []
    blocked: list[int] = []
    for x in bu:
        try:
            blocked.append(int(x))
        except (TypeError, ValueError):
            continue
    return {
        "group_id": int(doc_or_row.group_id),
        "roulette_mode": int(getattr(doc_or_row, "roulette_mode", 1)),
        "banned": bool(getattr(doc_or_row, "banned", False)),
        "sing_progress": _jsonable_sing_progress(sp),
        "disabled_plugins": list(doc_or_row.disabled_plugins or []),
        "blocked_user_ids": sorted(set(blocked)),
    }


def user_config_to_public(doc_or_row: Any) -> dict[str, Any]:
    if isinstance(doc_or_row, tuple):
        doc_or_row = doc_or_row[0]
    return {
        "user_id": int(doc_or_row.user_id),
        "banned": bool(getattr(doc_or_row, "banned", False)),
    }


def _is_pg_backend(name: str) -> bool:
    n = (name or "").lower()
    return n in ("postgresql", "postgres", "pg")


async def _pg_exact_row_count(model: type) -> int:
    from sqlalchemy import func, select

    from src.foundation.db.repository_pg import get_session

    async with get_session(read_only=True) as session:
        count = (await session.execute(select(func.count()).select_from(model))).scalar_one()
        return int(count)


async def _pg_estimate_row_count(model: type) -> int:
    from sqlalchemy import text

    from src.foundation.db.repository_pg import get_session

    table = getattr(model, "__table__", None)
    table_name = getattr(table, "name", None)
    if not table_name:
        return await _pg_exact_row_count(model)

    async with get_session(read_only=True) as session:
        estimate = (
            await session.execute(
                text("SELECT reltuples FROM pg_class WHERE oid = to_regclass(:table_name)"),
                {"table_name": table_name},
            )
        ).scalar_one_or_none()

    if estimate is None:
        return await _pg_exact_row_count(model)
    return max(0, int(float(estimate)))


async def list_all_bot_configs_public() -> list[dict[str, Any]]:
    backend = get_db_backend()
    if backend == "mongodb":
        from src.foundation.db.modules import BotConfigModule

        docs = await BotConfigModule.find().limit(_BOT_LIST_CAP).to_list()
        return [bot_config_to_public(d) for d in docs]
    if _is_pg_backend(backend):
        from sqlalchemy import select

        from src.foundation.db.repository_pg import BotConfigRow, get_session

        async with get_session(read_only=True) as session:
            result = await session.execute(select(BotConfigRow).limit(_BOT_LIST_CAP))
            rows = list(result.scalars().all())
        return [bot_config_to_public(r) for r in rows]
    raise ValueError(f"不支持的 DB 后端: {backend}")


async def list_group_configs_public(limit: int) -> list[dict[str, Any]]:
    cap = max(1, min(limit, _GROUP_LIST_CAP))
    backend = get_db_backend()
    if backend == "mongodb":
        from src.foundation.db.modules import GroupConfigModule

        docs = await GroupConfigModule.find().limit(cap).to_list()
        return [group_config_to_public(d) for d in docs]
    if _is_pg_backend(backend):
        from sqlalchemy import select

        from src.foundation.db.repository_pg import GroupConfigRow, get_session

        async with get_session(read_only=True) as session:
            result = await session.execute(select(GroupConfigRow).limit(cap))
            rows = list(result.scalars().all())
        return [group_config_to_public(r) for r in rows]
    raise ValueError(f"不支持的 DB 后端: {backend}")


async def list_user_configs_public(limit: int) -> list[dict[str, Any]]:
    cap = max(1, min(limit, _USER_LIST_CAP))
    backend = get_db_backend()
    if backend == "mongodb":
        from src.foundation.db.modules import UserConfigModule

        docs = await UserConfigModule.find().limit(cap).to_list()
        return [user_config_to_public(d) for d in docs]
    if _is_pg_backend(backend):
        from sqlalchemy import select

        from src.foundation.db.repository_pg import UserConfigRow, get_session

        async with get_session(read_only=True) as session:
            result = await session.execute(select(UserConfigRow).limit(cap))
            rows = list(result.scalars().all())
        return [user_config_to_public(r) for r in rows]
    raise ValueError(f"不支持的 DB 后端: {backend}")


async def list_group_configs_by_ids_public(group_ids: list[int]) -> dict[int, dict[str, Any]]:
    """按 group_id 列表批量读取群配置，返回 {group_id: config_dict}，用于按账号过滤群列表。"""
    if not group_ids:
        return {}
    ids = group_ids[:_GROUP_LIST_CAP]
    backend = get_db_backend()
    if backend == "mongodb":
        from src.foundation.db.modules import GroupConfigModule

        docs = await GroupConfigModule.find({"group_id": {"$in": ids}}).to_list()
        return {int(d.group_id): group_config_to_public(d) for d in docs}
    if _is_pg_backend(backend):
        from sqlalchemy import select

        from src.foundation.db.repository_pg import GroupConfigRow, get_session

        async with get_session(read_only=True) as session:
            result = await session.execute(select(GroupConfigRow).where(GroupConfigRow.group_id.in_(ids)))
            rows = list(result.scalars().all())
        return {int(r.group_id): group_config_to_public(r) for r in rows}
    raise ValueError(f"不支持的 DB 后端: {backend}")


async def database_overview() -> dict[str, Any]:
    """只读元数据 + 行数估计，供管理页概览；不含任意 SQL/聚合管道。"""
    backend = get_db_backend()
    if backend == "mongodb":
        from src.foundation.db.modules import (
            BlackList,
            BotConfigModule,
            Context,
            GroupConfigModule,
            ImageCache,
            Message,
            UserConfigModule,
        )

        async def _cnt(model: type, *, estimated: bool) -> int:
            coll = model.get_pymongo_collection()
            if estimated:
                return int(await coll.estimated_document_count())
            return int(await coll.count_documents({}))

        mongo_specs: list[tuple[str, str, type, bool]] = [
            ("config", "BotConfigModule", BotConfigModule, False),
            ("group_config", "GroupConfigModule", GroupConfigModule, False),
            ("user_config", "UserConfigModule", UserConfigModule, False),
            ("message", "Message", Message, True),
            ("context", "Context", Context, True),
            ("blacklist", "BlackList", BlackList, False),
            ("image_cache", "ImageCache", ImageCache, True),
        ]
        counts = await asyncio.gather(*(_cnt(m, estimated=est) for _, _, m, est in mongo_specs))
        return {
            "backend": "mongodb",
            "collections": [
                {
                    "name": name,
                    "document": doc,
                    "count": count,
                    "count_estimated": estimated,
                }
                for (name, doc, _, estimated), count in zip(mongo_specs, counts, strict=True)
            ],
        }
    if _is_pg_backend(backend):
        from src.foundation.db.repository_pg import (
            BlackListRow,
            BotConfigRow,
            ContextRow,
            GroupConfigRow,
            ImageCacheRow,
            MessageRow,
            UserConfigRow,
        )

        tables: list[tuple[str, type, bool]] = [
            ("bot_config", BotConfigRow, False),
            ("group_config", GroupConfigRow, False),
            ("user_config", UserConfigRow, False),
            ("message", MessageRow, True),
            ("context", ContextRow, True),
            ("blacklist", BlackListRow, False),
            ("image_cache", ImageCacheRow, True),
        ]

        counts = await asyncio.gather(
            *(
                _pg_estimate_row_count(model) if estimated else _pg_exact_row_count(model)
                for _, model, estimated in tables
            )
        )
        out = [
            {"table": name, "count": count, "count_estimated": estimated}
            for (name, _, estimated), count in zip(tables, counts, strict=True)
        ]
        return {"backend": "postgres", "tables": out}
    return {"backend": backend, "note": "未实现该后端的概览"}


_MONGO_AGG_COLLECTIONS: dict[str, type] = {}
_SAFE_AGG_OPS = frozenset({"$match", "$project", "$sort", "$limit", "$skip"})


def _mongo_agg_models() -> dict[str, type]:
    if _MONGO_AGG_COLLECTIONS:
        return _MONGO_AGG_COLLECTIONS
    from src.foundation.db.modules import (
        BlackList,
        BotConfigModule,
        Context,
        GroupConfigModule,
        ImageCache,
        Message,
        UserConfigModule,
    )

    _MONGO_AGG_COLLECTIONS.update({
        "config": BotConfigModule,
        "group_config": GroupConfigModule,
        "user_config": UserConfigModule,
        "message": Message,
        "context": Context,
        "blacklist": BlackList,
        "image_cache": ImageCache,
    })
    return _MONGO_AGG_COLLECTIONS


def _validate_mongo_aggregate_pipeline(pipeline: list[Any]) -> None:
    if len(pipeline) > 16:
        raise ValueError("pipeline 阶段数不得超过 16")
    for i, stage in enumerate(pipeline):
        if not isinstance(stage, dict):
            raise ValueError(f"阶段 {i} 必须为 JSON 对象")
        if len(stage) != 1:
            raise ValueError(f"阶段 {i} 只能包含一个顶层操作符（如仅 $match）")
        op = next(iter(stage))
        if op not in _SAFE_AGG_OPS:
            raise ValueError(f"不允许的聚合阶段: {op}（仅允许 $match/$project/$sort/$limit/$skip）")
        if op == "$limit":
            lim = stage["$limit"]
            if not isinstance(lim, int) or not (1 <= lim <= 500):
                raise ValueError("$limit 须为 1..500 的整数")
        if op == "$skip":
            sk = stage["$skip"]
            if not isinstance(sk, int) or not (0 <= sk <= 100_000):
                raise ValueError("$skip 须为 0..100000 的整数")


async def mongo_aggregate_console(*, collection: str, pipeline: list[Any]) -> list[dict[str, Any]]:
    """控制台用受限 aggregate；调用方须已通过 HTTP token 与后端非 Mongo 校验。"""
    backend = get_db_backend()
    if backend != "mongodb":
        raise ValueError("当前数据库后端不是 MongoDB，不支持 aggregate 管道")
    name = (collection or "").strip()
    models = _mongo_agg_models()
    if name not in models:
        raise ValueError("集合名不在允许列表（与概览页各集合一致）")
    _validate_mongo_aggregate_pipeline(pipeline)
    coll = models[name].get_pymongo_collection()
    capped: list[Any] = list(pipeline) + [{"$limit": 200}]
    cursor = coll.aggregate(capped, allowDiskUse=False)
    out: list[dict[str, Any]] = []
    n = 0
    async for doc in cursor:
        out.append(dict(doc))
        n += 1
        if n >= 200:
            break
    return out


def pallas_protocol_snapshot() -> dict[str, Any] | None:
    """
    pallas_protocol 插件已 **由 NoneBot 加载** 时返回元数据 + 账号列表；未加载为 None。
    不直接 import 插件包，避免在未加载时执行其 __init__ 重复挂路由。
    """
    from nonebot import get_loaded_plugins

    for p in get_loaded_plugins():
        mod = getattr(p, "module", None)
        mname = getattr(mod, "__name__", "")
        if mname != "src.plugins.pallas_protocol":
            continue
        cfg = getattr(mod, "plugin_config", None)
        mgr = getattr(mod, "manager", None)
        if cfg is None or mgr is None:
            return None
        from src.plugins.pallas_protocol.contract import resolve_public_mount_path

        path = resolve_public_mount_path(
            path_override=str(getattr(cfg, "pallas_protocol_webui_path", "") or ""),
            implementation_slug=str(getattr(cfg, "pallas_protocol_web_implementation", "") or ""),
        )
        try:
            accounts = mgr.list_accounts()
        except Exception:  # noqa: BLE001
            accounts = []
        try:
            from src.console.webui.console_login import is_console_auth_configured

            auth_ok = is_console_auth_configured()
        except Exception:  # noqa: BLE001
            auth_ok = False
        return {
            "plugin": "pallas_protocol",
            "webui_enabled": bool(getattr(cfg, "pallas_protocol_webui_enabled", False)),
            "webui_path": path,
            "console_auth_configured": auth_ok,
            "accounts": accounts,
        }
    return None
