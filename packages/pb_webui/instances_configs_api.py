"""Pallas-Bot WebUI console API: instances and bot/group/user configs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from nonebot import logger
from pydantic import BaseModel, ConfigDict, Field

from pallas.product.persona.account_profile import AccountPersonaProfile  # noqa: TC001

from .console_read_cache import cached_read, drop_read_cache
from .extended_common import (
    check_pallas_write_token,
)

if TYPE_CHECKING:
    from .config import Config


async def _instances_payload() -> dict[str, Any]:
    from pallas.core.foundation.db.pallas_console_data import list_all_bot_configs_public, pallas_protocol_snapshot
    from pallas.core.platform.bot_runtime.plugin_matrix import protocol_extension_status

    from .social_api import _collect_online_bot_profiles
    from .system_home_api import _list_bots_dict

    db_bots = await list_all_bot_configs_public()
    snap = pallas_protocol_snapshot()
    db_accounts = [int(b["account"]) for b in db_bots if isinstance(b, dict) and b.get("account") is not None]
    bot_profiles = await _collect_online_bot_profiles(ensure_accounts=db_accounts)
    payload: dict[str, Any] = {
        "nonebot_bots": _list_bots_dict(),
        "db_bot_configs": db_bots,
        "pallas_protocol": snap,
        "protocol_extension": protocol_extension_status(),
        "bot_profiles": bot_profiles,
    }
    if snap is not None:
        payload["napcat"] = snap
    return payload


async def _apply_bot_config_patch(account: int, body: _BotConfigPatch) -> dict[str, Any]:
    from pallas.core.foundation.db import make_bot_config_repository
    from pallas.core.foundation.db.pallas_console_data import bot_config_to_public

    repo = make_bot_config_repository()
    await repo.get_or_create(account, disabled_plugins=[])
    fields: dict[str, Any] = {}
    patch_data = body.model_dump(exclude_none=True)
    if "persona" in body.model_fields_set and body.persona is not None:
        patch_data["persona"] = body.persona.model_dump(exclude_unset=True)
    for field_name, raw in patch_data.items():
        if field_name in ("admins", "disabled_plugins") and raw is not None:
            if field_name == "disabled_plugins":
                fields[field_name] = [str(s).strip() for s in raw if str(s).strip()]
            else:
                fields[field_name] = [int(x) for x in raw]
        else:
            fields[field_name] = raw
    if "persona" in fields:
        from pallas.product.persona.seed import merge_persona_with_seed_patch

        incoming = fields.get("persona")
        if (
            isinstance(incoming, dict)
            and any(key in incoming for key in ("account_profile", "seed_override", "seed"))
            and not any(key in incoming for key in ("source", "derived", "version"))
        ):
            current = await repo.get(account)
            existing = getattr(current, "persona", None) if current is not None else None
            fields["persona"] = merge_persona_with_seed_patch(
                existing if isinstance(existing, dict) else None,
                incoming,
                bot_id=account,
            )
    await repo.upsert_fields(account, fields)
    if "disabled_plugins" in fields:
        from packages.help.plugin_manager import apply_disabled_plugin_config_change

        await apply_disabled_plugin_config_change(bot_id=account, disabled_plugins=fields["disabled_plugins"])
    if "admins" in fields:
        from pallas.core.foundation.config.bot_admins_cache import invalidate_bot_admins_cache

        await invalidate_bot_admins_cache(account)
    if "persona" in fields:
        from pallas.product.persona import invalidate_persona_cache

        invalidate_persona_cache(account)
    doc = await repo.get(account, ignore_cache=True)
    if doc is None:
        raise HTTPException(status_code=500, detail="config upsert 后回读失败")
    return bot_config_to_public(doc)


async def _apply_group_config_patch(group_id: int, body: _GroupConfigPatch) -> dict[str, Any]:
    from pallas.core.foundation.db import make_group_config_repository
    from pallas.core.foundation.db.pallas_console_data import group_config_to_public

    repo = make_group_config_repository()
    await repo.get_or_create(group_id, disabled_plugins=[])
    fields: dict[str, Any] = {}
    for field_name, raw in body.model_dump(exclude_none=True).items():
        if field_name == "disabled_plugins" and raw is not None:
            fields[field_name] = [str(s).strip() for s in raw if str(s).strip()]
        elif field_name == "roulette_mode":
            fields[field_name] = 1 if int(raw) == 1 else 0
        elif field_name == "blocked_user_ids" and raw is not None:
            # blocked_user_ids 逐项 int 转换
            fields[field_name] = [int(x) for x in raw]
        else:
            fields[field_name] = raw
    await repo.upsert_fields(group_id, fields)
    if "blocked_user_ids" in fields:
        from packages.blacklist import apply_group_blocked_users_change

        await apply_group_blocked_users_change(group_id, fields["blocked_user_ids"])
    if "banned" in fields:
        from packages.blacklist import apply_group_banned_change

        await apply_group_banned_change(group_id, bool(fields["banned"]))
    if "disabled_plugins" in fields:
        from packages.help.plugin_manager import apply_disabled_plugin_config_change

        await apply_disabled_plugin_config_change(group_id=group_id, disabled_plugins=fields["disabled_plugins"])
    doc = await repo.get(group_id, ignore_cache=True)
    if doc is None:
        raise HTTPException(status_code=500, detail="config upsert 后回读失败")
    return group_config_to_public(doc)


async def _apply_user_config_patch(user_id: int, body: _UserConfigPatch) -> dict[str, Any]:
    from pallas.core.foundation.db import make_user_config_repository
    from pallas.core.foundation.db.pallas_console_data import user_config_to_public

    repo = make_user_config_repository()
    await repo.get_or_create(user_id, banned=False)
    fields = body.model_dump(exclude_none=True)
    await repo.upsert_fields(user_id, fields)
    if "banned" in fields:
        from packages.blacklist import apply_user_banned_change

        await apply_user_banned_change(user_id, bool(fields["banned"]))
    doc = await repo.get(user_id, ignore_cache=True)
    if doc is None:
        raise HTTPException(status_code=500, detail="user_config upsert 后回读失败")
    return user_config_to_public(doc)


class _BotPersonaPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_profile: AccountPersonaProfile | None = None


class _BotConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admins: list[int] | None = None
    disabled_plugins: list[str] | None = None
    auto_accept_friend: bool | None = None
    auto_accept_group: bool | None = None
    security: bool | None = None
    community_roster_show_qq: bool | None = None
    persona: _BotPersonaPatch | None = None
    group_style_enabled: bool | None = None


class _GroupConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disabled_plugins: list[str] | None = None
    roulette_mode: int | None = Field(default=None, ge=0, le=1)
    banned: bool | None = None
    blocked_user_ids: list[int] | None = None


class _UserConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    banned: bool | None = None


def register_instances_configs_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    router_pub: APIRouter | None = None,
) -> None:
    """Register console routes."""

    @router.get(f"{x}/instances", include_in_schema=True)
    async def _instances() -> JSONResponse:
        try:
            payload = await cached_read(
                key="instances",
                loader=_instances_payload,
                ttl_sec=1.0,
                stale_sec=20.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 加载实例视图失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": payload})

    @router.get(f"{x}/bot-configs", include_in_schema=True)
    async def _bot_configs_list() -> JSONResponse:
        from pallas.core.foundation.db.pallas_console_data import list_all_bot_configs_public

        try:
            rows = await cached_read(
                key="bot_configs_list",
                loader=list_all_bot_configs_public,
                ttl_sec=1.0,
                stale_sec=20.0,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": rows})

    @router.get(f"{x}/bot-configs/{{account}}", include_in_schema=True)
    async def _bot_config_one(
        account: int,
    ) -> JSONResponse:
        from pallas.core.foundation.db import make_bot_config_repository
        from pallas.core.foundation.db.pallas_console_data import bot_config_to_public

        repo = make_bot_config_repository()
        doc = await repo.get(account, ignore_cache=True)
        if doc is None:
            raise HTTPException(status_code=404, detail="未找到该账号的 Bot 配置")
        return JSONResponse({"ok": True, "data": bot_config_to_public(doc)})

    @router.put(f"{x}/bot-configs/{{account}}", include_in_schema=True)
    async def _bot_config_put(
        account: int,
        body: _BotConfigPatch,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if not body.model_dump(exclude_none=True):
            raise HTTPException(status_code=400, detail="body 为空")
        try:
            data = await _apply_bot_config_patch(account, body)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 更新 Bot 配置失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        logger.info("[WebUI] 更新 Bot 配置成功，account [{}]", account)
        drop_read_cache(("instances", "bot_configs_list", "db_overview", "home-overview"))
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/group-configs", include_in_schema=True)
    async def _group_configs_list(
        limit: int = Query(default=1000, ge=1, le=10_000),
        self_id: int | None = Query(default=None, description="Bot QQ；传入时仅返回该 Bot 所在群的配置"),
    ) -> JSONResponse:
        from pallas.core.foundation.db.pallas_console_data import (
            list_group_configs_by_ids_public,
            list_group_configs_public,
        )

        # 按账号过滤：拉取 Bot 的群列表，再从 DB 取对应群配置并合并
        if self_id is not None:
            cache_key_bot = f"group_configs_bot:{int(self_id)}:{int(limit)}"

            async def _load_bot_merge() -> dict[str, Any]:
                from .social_api import _console_bot_connection_meta, _fetch_group_list_for_self_id

                _console_bot_connection_meta(int(self_id))
                groups_inner, err, truncated = await _fetch_group_list_for_self_id(
                    int(self_id),
                    limit=int(limit),
                )
                group_ids = [int(g["group_id"]) for g in groups_inner]

                try:
                    db_configs = await list_group_configs_by_ids_public(group_ids)
                except Exception as e:  # noqa: BLE001
                    raise HTTPException(status_code=500, detail=str(e)) from e

                rows_inner: list[dict[str, Any]] = []
                for g in groups_inner:
                    gid = int(g["group_id"])
                    cfg = db_configs.get(
                        gid,
                        {
                            "group_id": gid,
                            "roulette_mode": 1,
                            "banned": False,
                            "sing_progress": None,
                            "disabled_plugins": [],
                            "blocked_user_ids": [],
                        },
                    )
                    rows_inner.append({
                        **cfg,
                        "group_name": g.get("group_name", ""),
                        "member_count": g.get("member_count", 0),
                    })

                return {
                    "rows": rows_inner,
                    "meta": {
                        "limit": limit,
                        "self_id": str(int(self_id)),
                        "from_bot": True,
                        "error": err,
                        "truncated": truncated,
                    },
                }

            try:
                packed = await cached_read(
                    key=cache_key_bot,
                    loader=_load_bot_merge,
                    ttl_sec=2.0,
                    stale_sec=22.0,
                )
            except HTTPException:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception("[WebUI] 群配置（按 Bot）加载失败")
                raise HTTPException(status_code=500, detail=str(e)) from e

            return JSONResponse({
                "ok": True,
                "data": packed["rows"],
                "meta": packed["meta"],
            })

        # 原有行为：返回 DB 中所有群配置
        cache_key = f"group_configs_list:{int(limit)}"

        async def _load() -> list[dict[str, Any]]:
            return await list_group_configs_public(limit)

        try:
            rows = await cached_read(key=cache_key, loader=_load, ttl_sec=1.0, stale_sec=20.0)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": rows, "meta": {"limit": limit}})

    @router.get(f"{x}/group-configs/{{group_id}}", include_in_schema=True)
    async def _group_config_one(
        group_id: int,
    ) -> JSONResponse:
        from pallas.core.foundation.db import make_group_config_repository
        from pallas.core.foundation.db.pallas_console_data import group_config_to_public

        repo = make_group_config_repository()
        doc, _created = await repo.get_or_create(group_id, disabled_plugins=[])
        return JSONResponse({"ok": True, "data": group_config_to_public(doc)})

    @router.put(f"{x}/group-configs/{{group_id}}", include_in_schema=True)
    async def _group_config_put(
        group_id: int,
        body: _GroupConfigPatch,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if not body.model_dump(exclude_none=True):
            raise HTTPException(status_code=400, detail="body 为空")
        try:
            data = await _apply_group_config_patch(group_id, body)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 更新群配置失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        logger.info("[WebUI] 更新群配置成功，group_id [{}]", group_id)
        drop_read_cache(("group_configs_list", "db_overview", "group_configs_bot:"))
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/user-configs", include_in_schema=True)
    async def _user_configs_list(
        limit: int = Query(default=1000, ge=1, le=10_000),
    ) -> JSONResponse:
        from pallas.core.foundation.db.pallas_console_data import list_user_configs_public

        cache_key = f"user_configs_list:{int(limit)}"

        async def _load() -> list[dict[str, Any]]:
            return await list_user_configs_public(limit)

        try:
            rows = await cached_read(key=cache_key, loader=_load, ttl_sec=1.0, stale_sec=20.0)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": rows, "meta": {"limit": limit}})

    @router.get(f"{x}/user-configs/{{user_id}}", include_in_schema=True)
    async def _user_config_one(
        user_id: int,
    ) -> JSONResponse:
        from pallas.core.foundation.db import make_user_config_repository
        from pallas.core.foundation.db.pallas_console_data import user_config_to_public

        repo = make_user_config_repository()
        doc, _created = await repo.get_or_create(user_id, banned=False)
        return JSONResponse({"ok": True, "data": user_config_to_public(doc)})

    @router.put(f"{x}/user-configs/{{user_id}}", include_in_schema=True)
    async def _user_config_put(
        user_id: int,
        body: _UserConfigPatch,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if not body.model_dump(exclude_none=True):
            raise HTTPException(status_code=400, detail="body 为空")
        try:
            data = await _apply_user_config_patch(user_id, body)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 更新 User 配置失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        logger.info("[WebUI] 更新 User 配置成功，user_id [{}]", user_id)
        drop_read_cache(("db_overview", "user_configs_list"))
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/bots/{{qq}}/disconnect-ws", include_in_schema=True)
    async def _bot_disconnect_ws(
        qq: int,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        """关闭本进程对该 QQ 的 OneBot WS（不停止外置协议端进程）。"""
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if qq < 1:
            raise HTTPException(status_code=400, detail="无效的 QQ")
        from pallas.core.platform.shard.presence import close_local_bot_connection

        closed = await close_local_bot_connection(int(qq))
        if not closed:
            raise HTTPException(
                status_code=404,
                detail="当前进程未找到该账号的 WS 连接（可能已断开，或不在本机）",
            )
        drop_read_cache(("instances", "bots", "home-overview"))
        return JSONResponse({"ok": True, "data": {"qq": int(qq), "closed": True}})
