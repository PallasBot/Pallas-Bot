"""Pallas-Bot WebUI console API: plugins console routes."""

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from nonebot import logger
from pydantic import BaseModel, ConfigDict, Field

from packages.pb_webui.console_openapi_models import (
    PluginConfigData as _PluginConfigData,
)
from packages.pb_webui.console_openapi_models import (
    PluginConfigRawData as _PluginConfigRawData,
)
from packages.pb_webui.console_openapi_models import (
    PluginGovernanceData as _PluginGovernanceData,
)
from packages.pb_webui.console_openapi_models import (
    _ApiOkResponse,
)
from pallas.console.webui import apply_plugin_config_patch, plugin_config_payload

from .config import Config
from .console_read_cache import cached_read, drop_read_cache
from .extended_common import (
    check_pallas_write_token,
)


def _metadata_to_dict(meta: object | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    d: dict[str, Any] = {
        "name": getattr(meta, "name", None),
        "description": (getattr(meta, "description", None) or "")[:2000],
        "usage": (getattr(meta, "usage", None) or "")[:4000],
    }
    ex = getattr(meta, "extra", None)
    if ex:
        d["extra"] = dict(ex) if isinstance(ex, dict) else ex
    typ = getattr(meta, "type", None)
    if typ is not None:
        d["type"] = str(typ)
    return d


def _help_menu_control() -> tuple[set[str], set[str]]:
    """返回 (help 忽略名单, 额外隐藏名单)。"""
    ignored: set[str] = set()
    hidden: set[str] = set()
    try:
        from packages.help.config import get_help_config
        from packages.help.visibility import resolve_help_hidden_plugins

        cfg = get_help_config()
        ignored = {str(x).strip() for x in list(getattr(cfg, "ignored_plugins", []) or []) if str(x).strip()}
        hidden = {str(x).strip() for x in resolve_help_hidden_plugins() if str(x).strip()}
    except Exception:
        pass
    return ignored, hidden


def _list_plugins_dict() -> list[dict[str, Any]]:
    from packages.help.global_disable import (
        GLOBAL_DISABLE_PROTECTED_PLUGINS,
        load_global_disabled_plugins,
    )
    from pallas.console.webui.plugin_catalog import build_plugin_catalog_rows

    ignored, hidden = _help_menu_control()
    return build_plugin_catalog_rows(
        ignored=ignored,
        hidden=hidden,
        globally_disabled=set(load_global_disabled_plugins()),
        global_disable_protected=set(GLOBAL_DISABLE_PROTECTED_PLUGINS),
    )


async def _scheduled_refresh_plugin_update_snapshot() -> None:
    """每日 4:00 比对插件版本，刷新「有无新版本」快照。"""
    from pallas.console.webui.plugin_update_snapshot import refresh_plugin_update_snapshot

    try:
        await refresh_plugin_update_snapshot()
        drop_read_cache(("plugins-community-store", "plugins-official-extensions"))
    except Exception:  # noqa: BLE001
        logger.exception("Pallas-Bot 控制台: 定时刷新插件更新快照失败")


async def _scheduled_refresh_plugin_store_assets() -> None:
    from pallas.console.webui.plugin_store_assets import refresh_store_asset_snapshot

    try:
        await refresh_store_asset_snapshot()
        drop_read_cache(("plugins-community-store", "plugins-official-extensions"))
    except Exception:  # noqa: BLE001
        logger.exception("Pallas-Bot 控制台: 定时刷新插件商店资源快照失败")


class _HelpMenuVisibilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hidden_plugins: list[str] = Field(default_factory=list, max_length=2000)


class _SystemRestartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workers_only: bool = False


class _OfficialExtensionPackageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package: str = Field(min_length=1, max_length=128)
    restart: bool = False


class _CommunityPluginActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str = Field(min_length=1, max_length=64)
    repository_url: str | None = Field(default=None, max_length=512)
    ref: str | None = Field(default=None, max_length=128)
    restart: bool = False


class _GlobalPluginDisableBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disabled_plugins: list[str] = Field(default_factory=list, max_length=2000)


class _PluginGovernanceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_permission_overrides: dict[str, str] = Field(default_factory=dict)
    command_limit_overrides: dict[str, int] = Field(default_factory=dict)
    global_disable: bool = False
    help_hidden: bool = False
    blocked_user_ids: list[int] = Field(default_factory=list)


class _GroupFleetWhitelistEntryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: int = Field(ge=1)
    plugins: list[str] = Field(default_factory=list, max_length=2000)


class _GroupFleetWhitelistBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[_GroupFleetWhitelistEntryBody] = Field(default_factory=list, max_length=5000)


class _PluginConfigUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(default_factory=dict)


class _PluginConfigRawBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    toml: str = ""


PluginConfigUpdateBody = _PluginConfigUpdateBody
PluginConfigRawBody = _PluginConfigRawBody
PluginGovernanceBody = _PluginGovernanceBody
OfficialExtensionPackageBody = _OfficialExtensionPackageBody
CommunityPluginActionBody = _CommunityPluginActionBody
HelpMenuVisibilityBody = _HelpMenuVisibilityBody
GlobalPluginDisableBody = _GlobalPluginDisableBody
GroupFleetWhitelistBody = _GroupFleetWhitelistBody


async def _resolve_community_plugin_target(body: CommunityPluginActionBody) -> tuple[str, str, str]:
    from pallas.console.cli.community_plugin_target import resolve_community_plugin_target
    from pallas.console.webui.community_plugin_install import CommunityPluginInstallError

    try:
        return await resolve_community_plugin_target(
            body.plugin_id,
            repository_url=body.repository_url,
            ref=body.ref or "main",
        )
    except CommunityPluginInstallError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e


def register_plugins_console_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    router_pub: APIRouter | None = None,
) -> None:
    """Register console routes."""

    @router.get(f"{x}/plugins", include_in_schema=True)
    async def _plugins() -> JSONResponse:
        async def _load() -> list[dict[str, Any]]:
            return _list_plugins_dict()

        data = await cached_read(key="plugins", loader=_load, ttl_sec=1.6, stale_sec=25.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/plugins/capabilities", include_in_schema=True)
    async def _plugins_capabilities() -> JSONResponse:
        from pallas.core.plugin_capabilities import build_plugin_capabilities_ui

        async def _load() -> dict[str, Any]:
            return build_plugin_capabilities_ui()

        data = await cached_read(key="plugins-capabilities", loader=_load, ttl_sec=2.0, stale_sec=30.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/plugins/store/readme", include_in_schema=True)
    async def _plugins_store_readme(
        kind: str = Query(..., description="official 或 community"),
        target_id: str = Query(..., alias="id", description="官方包名或社区 plugin_id"),
        repository_url: str | None = Query(default=None, description="仓库地址，缓存未命中时按需拉取 README"),
    ) -> JSONResponse:
        from pallas.console.webui.plugin_store_assets import (
            fetch_and_cache_readme_markdown,
            get_cached_readme_markdown,
            resolve_readme_request_id,
        )

        if kind not in {"official", "community"}:
            raise HTTPException(status_code=400, detail="kind must be official or community")
        resolved_id = resolve_readme_request_id(kind, target_id)
        markdown = get_cached_readme_markdown(kind, resolved_id)
        if markdown is None:
            markdown = await fetch_and_cache_readme_markdown(
                kind,
                resolved_id,
                repository_url=repository_url,
            )
        if markdown is None:
            raise HTTPException(status_code=404, detail="README not available")
        return JSONResponse({"ok": True, "data": {"kind": kind, "id": resolved_id, "markdown": markdown}})

    @router.get(f"{x}/plugins/store/changelog", include_in_schema=True)
    async def _plugins_store_changelog(
        kind: str = Query(..., description="official 或 community"),
        target_id: str = Query(..., alias="id", description="官方包名或社区 plugin_id"),
        repository_url: str | None = Query(default=None, description="仓库地址，缓存未命中时按需拉取 CHANGELOG.md"),
    ) -> JSONResponse:
        from pallas.console.webui.plugin_store_assets import (
            fetch_and_cache_changelog_markdown,
            get_cached_changelog_markdown,
            resolve_readme_request_id,
        )

        if kind not in {"official", "community"}:
            raise HTTPException(status_code=400, detail="kind must be official or community")
        resolved_id = resolve_readme_request_id(kind, target_id)
        markdown = get_cached_changelog_markdown(kind, resolved_id)
        source = "changelog"
        if markdown is None:
            markdown = await fetch_and_cache_changelog_markdown(
                kind,
                resolved_id,
                repository_url=repository_url,
            )
        if markdown is None and kind == "community":
            # 社区插件未提供 CHANGELOG.md 时，回退到本地 git 提交历史自动生成。
            from pallas.console.webui.community_plugin_changelog import (
                generate_community_changelog_from_git,
            )

            markdown = await generate_community_changelog_from_git(resolved_id)
            if markdown is not None:
                source = "git"
        if markdown is None:
            raise HTTPException(status_code=404, detail="Changelog not available")
        return JSONResponse(
            {"ok": True, "data": {"kind": kind, "id": resolved_id, "markdown": markdown, "source": source}},
        )

    @router.get(f"{x}/plugins/{{plugin_name}}/readme", include_in_schema=True)
    async def _plugin_bundled_readme(plugin_name: str) -> JSONResponse:
        from pallas.console.webui.plugin_docs_readme import read_bundled_plugin_readme

        target = (plugin_name or "").strip()
        if not target:
            raise HTTPException(status_code=400, detail="plugin_name required")
        payload = read_bundled_plugin_readme(target)
        if payload is None:
            raise HTTPException(status_code=404, detail=f"README not found for plugin: {target}")
        return JSONResponse({"ok": True, "data": payload})

    @router.get(
        f"{x}/plugins/{{plugin_name}}/governance",
        include_in_schema=True,
        response_model=_ApiOkResponse[_PluginGovernanceData],
    )
    async def _plugin_governance_get(plugin_name: str) -> dict[str, Any]:
        from packages.help.global_disable import load_global_disabled_plugins
        from packages.help.visibility import load_help_hidden_plugins
        from pallas.console.webui.plugin_governance import (
            canonical_plugin_name,
            enrich_commands_with_menu_triggers,
            find_capability_plugin_row,
            find_catalog_plugin_row,
            governance_row_from_catalog,
        )
        from pallas.core.limits.config import get_command_limits_config, normalize_command_limit_overrides
        from pallas.core.limits.schema import build_command_limits_ui
        from pallas.core.perm.config import get_cmd_perm_config
        from pallas.core.perm.plugin_acl import list_plugin_blocked_user_ids
        from pallas.core.perm.schema import build_command_perm_ui
        from pallas.core.plugin_capabilities import build_plugin_capabilities_ui

        target = canonical_plugin_name(plugin_name)
        if not target:
            raise HTTPException(status_code=400, detail="plugin_name required")

        capabilities = build_plugin_capabilities_ui()
        catalog_rows = _list_plugins_dict()
        plugin_row = find_capability_plugin_row(capabilities, target)
        plugin_meta = find_catalog_plugin_row(catalog_rows, target) or {}
        if plugin_row is None:
            if not plugin_meta:
                raise HTTPException(status_code=404, detail=f"unknown plugin: {target}")
            plugin_row = governance_row_from_catalog(target, plugin_meta)

        metadata = plugin_meta.get("metadata") if isinstance(plugin_meta, dict) else {}
        extra = metadata.get("extra") if isinstance(metadata, dict) else {}
        menu_items = list(extra.get("menu_data") or []) if isinstance(extra, dict) else []

        perm_cfg = get_cmd_perm_config()
        perm_ui = build_command_perm_ui(
            {str(k): str(v) for k, v in (perm_cfg.command_permission_overrides or {}).items()},
        )
        perm_row = find_capability_plugin_row(perm_ui, target) or {}

        limits_cfg = get_command_limits_config()
        limits_ui = build_command_limits_ui(
            normalize_command_limit_overrides(limits_cfg.command_limit_overrides or {}),
        )
        limits_row = find_capability_plugin_row(limits_ui, target) or {}
        if menu_items:
            if perm_row:
                perm_row = {
                    **perm_row,
                    "commands": enrich_commands_with_menu_triggers(
                        list(perm_row.get("commands") or []),
                        menu_items,
                    ),
                }
            if limits_row:
                limits_row = {
                    **limits_row,
                    "commands": enrich_commands_with_menu_triggers(
                        list(limits_row.get("commands") or []),
                        menu_items,
                    ),
                }

        runtime_ids = {target}
        for key in ("name", "resolved_plugin_id", "nb_plugin_name"):
            value = str(plugin_meta.get(key) or "").strip()
            if value:
                runtime_ids.add(value)
                runtime_ids.add(canonical_plugin_name(value))
        hidden = {str(x).strip() for x in load_help_hidden_plugins() if str(x).strip()}
        disabled = {str(x).strip() for x in load_global_disabled_plugins() if str(x).strip()}
        commands = enrich_commands_with_menu_triggers(
            list(plugin_row.get("commands") or []),
            menu_items,
        )
        blocked_user_ids = await list_plugin_blocked_user_ids(target)
        return {
            "ok": True,
            "data": {
                "plugin": target,
                "title": str(plugin_row.get("title") or target),
                "commands": commands,
                "menu_items": menu_items,
                "runtime": {
                    "global_disable": any(item in disabled for item in runtime_ids),
                    "help_hidden": any(item in hidden for item in runtime_ids),
                    "global_disable_protected": bool(plugin_meta.get("global_disable_protected")),
                    "help_ignored": bool(plugin_meta.get("help_ignored")),
                },
                "perm_ui_filtered": {
                    "levels": list(perm_ui.get("levels") or []),
                    "plugins": [perm_row] if perm_row else [],
                },
                "limits_ui_filtered": {
                    "plugins": [limits_row] if limits_row else [],
                },
                "blocked_user_ids": blocked_user_ids,
                "reload_policy": plugin_row.get("reload_policy"),
                "activation_policy": plugin_row.get("activation_policy"),
            },
        }

    @router.put(f"{x}/plugins/{{plugin_name}}/governance", include_in_schema=True)
    async def _plugin_governance_put(
        plugin_name: str,
        body: PluginGovernanceBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)

        from pallas.console.webui.plugin_governance import canonical_plugin_name

        target = canonical_plugin_name(plugin_name)
        if not target:
            raise HTTPException(status_code=400, detail="plugin_name required")

        from packages.help.global_disable import load_global_disabled_plugins, save_global_disabled_plugins
        from packages.help.plugin_manager import invalidate_disabled_plugin_gate_cache
        from packages.help.visibility import load_help_hidden_plugins, save_help_hidden_plugins
        from pallas.api.config import upsert_repo_settings_items
        from pallas.core.limits.config import get_command_limits_config, normalize_command_limit_overrides
        from pallas.core.perm.config import get_cmd_perm_config
        from pallas.core.perm.plugin_acl import sync_plugin_blocked_user_ids
        from pallas.core.perm.ui_labels import plugin_name_for_command_id

        target_ids = {
            str(cid).strip()
            for cid in (
                list((body.command_permission_overrides or {}).keys())
                + list((body.command_limit_overrides or {}).keys())
            )
            if str(cid).strip() and plugin_name_for_command_id(str(cid).strip()) == target
        }

        current_perm_overrides = {
            str(k): str(v) for k, v in (get_cmd_perm_config().command_permission_overrides or {}).items()
        }
        current_limit_overrides = normalize_command_limit_overrides(
            get_command_limits_config().command_limit_overrides or {},
        )

        perm_overrides = {
            str(k): str(v) for k, v in (body.command_permission_overrides or {}).items() if str(k).strip() in target_ids
        }
        limit_overrides = {
            str(k): int(v) for k, v in (body.command_limit_overrides or {}).items() if str(k).strip() in target_ids
        }
        env_items: dict[str, str] = {}
        if target_ids:
            merged_perm_overrides = {
                cid: level for cid, level in current_perm_overrides.items() if cid not in target_ids
            }
            merged_perm_overrides.update(perm_overrides)
            env_items["PALLAS_COMMAND_PERMISSION_OVERRIDES"] = json.dumps(
                merged_perm_overrides,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if target_ids:
            merged_limit_overrides = {cid: cd for cid, cd in current_limit_overrides.items() if cid not in target_ids}
            merged_limit_overrides.update(limit_overrides)
            env_items["PALLAS_COMMAND_LIMIT_OVERRIDES"] = json.dumps(
                merged_limit_overrides,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if env_items:
            upsert_repo_settings_items(env_items)
            if "PALLAS_COMMAND_PERMISSION_OVERRIDES" in env_items:
                from pallas.core.perm.config import clear_cmd_perm_cache

                clear_cmd_perm_cache()
            if "PALLAS_COMMAND_LIMIT_OVERRIDES" in env_items:
                from pallas.core.limits.config import clear_command_limits_cache

                clear_command_limits_cache()

        hidden = set(load_help_hidden_plugins())
        if body.help_hidden:
            hidden.add(target)
        else:
            hidden.discard(target)
        hidden_saved = save_help_hidden_plugins(sorted(hidden))

        disabled = set(load_global_disabled_plugins())
        if body.global_disable:
            disabled.add(target)
        else:
            disabled.discard(target)
        disabled_saved = save_global_disabled_plugins(sorted(disabled))
        await invalidate_disabled_plugin_gate_cache(clear_all=True)

        blocked_saved = await sync_plugin_blocked_user_ids(target, list(body.blocked_user_ids or []))

        drop_read_cache(("plugins", "plugins-capabilities", "home-overview"))
        return JSONResponse({
            "ok": True,
            "data": {
                "plugin": target,
                "command_permission_overrides": perm_overrides,
                "command_limit_overrides": limit_overrides,
                "blocked_user_ids": blocked_saved,
                "runtime": {
                    "global_disable": target in disabled_saved,
                    "help_hidden": target in hidden_saved,
                },
            },
        })

    @router.post(f"{x}/plugins/{{plugin_name}}/reload", include_in_schema=True)
    async def _plugin_reload(
        plugin_name: str,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.core.plugin_reload.reload_ops import PluginReloadError, execute_plugin_reload

        target = (plugin_name or "").strip()
        if not target:
            raise HTTPException(status_code=400, detail="plugin_name required")

        try:
            data = execute_plugin_reload(target)
        except PluginReloadError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e

        drop_read_cache(("plugins", "plugins-capabilities", "home-overview"))
        status = 200 if data.get("ok") else 409
        return JSONResponse({"ok": bool(data.get("ok")), "data": data}, status_code=status)

    @router.get(f"{x}/plugins/official-extensions", include_in_schema=True)
    async def _plugins_official_extensions() -> JSONResponse:
        from pallas.console.webui.plugin_registry import build_official_extension_rows
        from pallas.console.webui.plugin_store_assets import (
            refresh_store_asset_snapshot,
            snapshot_has_assets_for_kind,
        )

        if not snapshot_has_assets_for_kind("official"):
            await refresh_store_asset_snapshot()

        async def _load() -> list[dict[str, Any]]:
            return build_official_extension_rows()

        data = await cached_read(key="plugins-official-extensions", loader=_load, ttl_sec=30.0, stale_sec=120.0)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/plugins/official-extensions/install", include_in_schema=True)
    async def _plugins_official_extensions_install(
        body: OfficialExtensionPackageBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.cli.extension_ops import (
            ExtensionInstallError,
            install_official_extension_with_options,
        )
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        try:
            data = await install_official_extension_with_options(
                body.package,
                restart=bool(body.restart),
            )
            drop_read_cache(("plugins-official-extensions", "plugins"))
            return JSONResponse({"ok": True, "data": data})
        except ExtensionInstallError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 安装官方扩展失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.post(f"{x}/plugins/official-extensions/install-async", include_in_schema=True)
    async def _plugins_official_extensions_install_async(
        body: OfficialExtensionPackageBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        import asyncio

        from pallas.console.cli.extension_ops import install_official_extension_with_options
        from pallas.console.webui.plugin_store_job_progress import (
            create_plugin_store_job,
            job_progress_reporter,
            run_plugin_store_job,
        )

        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        job = await create_plugin_store_job(kind="official", target=body.package, action="install")

        async def runner(j) -> None:
            data = await install_official_extension_with_options(
                j.target,
                restart=bool(body.restart),
                on_progress=job_progress_reporter(j),
            )
            drop_read_cache(("plugins-official-extensions", "plugins"))
            j.result = dict(data)
            j.message = str(data.get("message") or "完成")

        asyncio.create_task(run_plugin_store_job(job, runner))
        return JSONResponse({"ok": True, "data": {"job_id": job.job_id, "package": job.target}})

    @router.post(f"{x}/plugins/official-extensions/update-async", include_in_schema=True)
    async def _plugins_official_extensions_update_async(
        body: OfficialExtensionPackageBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        import asyncio

        from pallas.console.cli.extension_ops import update_official_extension_with_options
        from pallas.console.webui.plugin_store_job_progress import (
            create_plugin_store_job,
            job_progress_reporter,
            run_plugin_store_job,
        )

        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        job = await create_plugin_store_job(kind="official", target=body.package, action="update")

        async def runner(j) -> None:
            data = await update_official_extension_with_options(
                j.target,
                restart=bool(body.restart),
                on_progress=job_progress_reporter(j),
            )
            drop_read_cache(("plugins-official-extensions", "plugins"))
            j.result = dict(data)
            j.message = str(data.get("message") or "完成")

        asyncio.create_task(run_plugin_store_job(job, runner))
        return JSONResponse({"ok": True, "data": {"job_id": job.job_id, "package": job.target}})

    @router.post(f"{x}/plugins/official-extensions/uninstall-async", include_in_schema=True)
    async def _plugins_official_extensions_uninstall_async(
        body: OfficialExtensionPackageBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        import asyncio

        from pallas.console.cli.extension_ops import uninstall_official_extension_with_options
        from pallas.console.webui.plugin_store_job_progress import (
            create_plugin_store_job,
            job_progress_reporter,
            run_plugin_store_job,
        )

        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        job = await create_plugin_store_job(kind="official", target=body.package, action="uninstall")

        async def runner(j) -> None:
            data = await uninstall_official_extension_with_options(
                j.target,
                restart=bool(body.restart),
                on_progress=job_progress_reporter(j),
            )
            drop_read_cache(("plugins-official-extensions", "plugins"))
            j.result = dict(data)
            j.message = str(data.get("message") or "完成")

        asyncio.create_task(run_plugin_store_job(job, runner))
        return JSONResponse({"ok": True, "data": {"job_id": job.job_id, "package": job.target}})

    def _store_job_stream_response(job_id: str) -> StreamingResponse:
        from pallas.console.webui.plugin_store_job_progress import iter_plugin_store_job_sse

        return StreamingResponse(
            iter_plugin_store_job_sse(job_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get(
        f"{x}/plugins/store-jobs/active",
        include_in_schema=True,
    )
    async def _plugins_store_job_active() -> JSONResponse:
        from pallas.console.webui.plugin_store_job_progress import get_active_plugin_store_job

        job = get_active_plugin_store_job()
        return JSONResponse({"ok": True, "data": job.as_dict() if job else None})

    @router.get(
        f"{x}/plugins/store-jobs/{{job_id}}",
        include_in_schema=True,
    )
    async def _plugins_store_job_get(job_id: str) -> JSONResponse:
        from pallas.console.webui.plugin_store_job_progress import get_plugin_store_job

        job = get_plugin_store_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        return JSONResponse({"ok": True, "data": job.as_dict()})

    @router.get(
        f"{x}/plugins/store-jobs/{{job_id}}/stream",
        include_in_schema=True,
    )
    async def _plugins_store_job_stream(job_id: str) -> StreamingResponse:
        return _store_job_stream_response(job_id)

    @router.get(
        f"{x}/plugins/official-extensions/install-jobs/{{job_id}}/stream",
        include_in_schema=True,
    )
    async def _plugins_official_extensions_install_job_stream(job_id: str) -> StreamingResponse:
        return _store_job_stream_response(job_id)

    @router.get(
        f"{x}/plugins/install-jobs/{{job_id}}/stream",
        include_in_schema=True,
    )
    async def _plugins_install_job_stream(job_id: str) -> StreamingResponse:
        return _store_job_stream_response(job_id)

    @router.post(f"{x}/plugins/official-extensions/uninstall", include_in_schema=True)
    async def _plugins_official_extensions_uninstall(
        body: OfficialExtensionPackageBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.cli.extension_ops import (
            ExtensionInstallError,
            uninstall_official_extension_with_options,
        )
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        try:
            data = await uninstall_official_extension_with_options(
                body.package,
                restart=bool(body.restart),
            )
            drop_read_cache(("plugins-official-extensions", "plugins"))
            return JSONResponse({"ok": True, "data": data})
        except ExtensionInstallError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 卸载官方扩展失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.post(f"{x}/plugins/official-extensions/update", include_in_schema=True)
    async def _plugins_official_extensions_update(
        body: OfficialExtensionPackageBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.cli.extension_ops import (
            ExtensionInstallError,
            update_official_extension_with_options,
        )
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        try:
            data = await update_official_extension_with_options(
                body.package,
                restart=bool(body.restart),
            )
            drop_read_cache(("plugins-official-extensions", "plugins"))
            return JSONResponse({"ok": True, "data": data})
        except ExtensionInstallError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 更新官方扩展失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.get(f"{x}/plugins/community-store", include_in_schema=True)
    async def _plugins_community_store(
        refresh: bool = Query(default=False, description="为 true 时跳过进程内读缓存并重新拉取索引"),
    ) -> JSONResponse:
        from pallas.console.webui.community_plugin_registry import build_community_plugin_store
        from pallas.console.webui.plugin_store_assets import (
            refresh_store_asset_snapshot,
            snapshot_has_assets_for_kind,
        )

        if refresh:
            drop_read_cache(("plugins-community-store",))
            await refresh_store_asset_snapshot()
        elif not snapshot_has_assets_for_kind("community"):
            await refresh_store_asset_snapshot()

        async def _load() -> dict[str, Any]:
            return await build_community_plugin_store()

        data = await cached_read(key="plugins-community-store", loader=_load, ttl_sec=30.0, stale_sec=120.0)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/plugins/store/refresh", include_in_schema=True)
    async def _plugins_store_refresh(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.webui.plugin_store_assets import refresh_store_asset_snapshot
        from pallas.console.webui.plugin_update_snapshot import refresh_plugin_update_snapshot
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        try:
            store_assets, update_snapshot = await asyncio.gather(
                refresh_store_asset_snapshot(),
                refresh_plugin_update_snapshot(),
            )
            drop_read_cache(("plugins-community-store", "plugins-official-extensions"))
            return JSONResponse({
                "ok": True,
                "data": {
                    "store_assets": {
                        "checked_at": store_assets.get("checked_at"),
                        "community_count": len(store_assets.get("community") or {}),
                        "official_count": len(store_assets.get("official") or {}),
                    },
                    "update_snapshot": {
                        "checked_at": update_snapshot.get("checked_at"),
                        "community_count": len(update_snapshot.get("community") or {}),
                        "official_count": len(update_snapshot.get("official") or {}),
                    },
                },
            })
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 刷新插件商店聚合数据失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.post(f"{x}/plugins/update-snapshot/refresh", include_in_schema=True)
    async def _plugins_update_snapshot_refresh(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        """手动比对全部插件版本，刷新「有无新版本」快照。"""
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.webui.plugin_update_snapshot import refresh_plugin_update_snapshot
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        try:
            snapshot = await refresh_plugin_update_snapshot()
            drop_read_cache(("plugins-community-store", "plugins-official-extensions"))
            return JSONResponse({
                "ok": True,
                "data": {
                    "checked_at": snapshot.get("checked_at"),
                    "community_count": len(snapshot.get("community") or {}),
                    "official_count": len(snapshot.get("official") or {}),
                },
            })
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 刷新插件更新快照失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.post(f"{x}/plugins/store-assets/refresh", include_in_schema=True)
    async def _plugins_store_assets_refresh(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.webui.plugin_store_assets import refresh_store_asset_snapshot
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        try:
            snapshot = await refresh_store_asset_snapshot()
            drop_read_cache(("plugins-community-store", "plugins-official-extensions"))
            return JSONResponse({
                "ok": True,
                "data": {
                    "checked_at": snapshot.get("checked_at"),
                    "community_count": len(snapshot.get("community") or {}),
                    "official_count": len(snapshot.get("official") or {}),
                },
            })
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 刷新插件商店资源快照失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.post(f"{x}/plugins/community-plugins/install", include_in_schema=True)
    async def _plugins_community_plugins_install(
        body: CommunityPluginActionBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.cli.community_plugin_ops import (
            CommunityPluginInstallError,
            install_community_plugin_with_options,
        )
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        try:
            plugin_id, repo_url, ref = await _resolve_community_plugin_target(body)
            data = await install_community_plugin_with_options(
                plugin_id,
                repository_url=repo_url,
                ref=ref,
                restart=bool(body.restart),
            )
            drop_read_cache(("plugins-community-store", "plugins"))
            return JSONResponse({"ok": True, "data": data})
        except CommunityPluginInstallError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 安装社区插件失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.post(f"{x}/plugins/community-plugins/install-async", include_in_schema=True)
    async def _plugins_community_plugins_install_async(
        body: CommunityPluginActionBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        import asyncio

        from pallas.console.cli.community_plugin_ops import install_community_plugin_with_options
        from pallas.console.webui.plugin_store_job_progress import (
            create_plugin_store_job,
            job_progress_reporter,
            run_plugin_store_job,
        )

        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        plugin_id, repo_url, ref = await _resolve_community_plugin_target(body)
        job = await create_plugin_store_job(kind="community", target=plugin_id, action="install")

        async def runner(j) -> None:
            data = await install_community_plugin_with_options(
                j.target,
                repository_url=repo_url,
                ref=ref,
                restart=bool(body.restart),
                on_progress=job_progress_reporter(j),
            )
            drop_read_cache(("plugins-community-store", "plugins"))
            j.result = dict(data)
            j.message = str(data.get("message") or "完成")

        asyncio.create_task(run_plugin_store_job(job, runner))
        return JSONResponse({"ok": True, "data": {"job_id": job.job_id, "package": plugin_id}})

    @router.post(f"{x}/plugins/community-plugins/update-async", include_in_schema=True)
    async def _plugins_community_plugins_update_async(
        body: CommunityPluginActionBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        import asyncio

        from pallas.console.cli.community_plugin_ops import update_community_plugin_with_options
        from pallas.console.webui.community_plugin_index import load_community_plugin_index_safe
        from pallas.console.webui.plugin_store_job_progress import (
            create_plugin_store_job,
            job_progress_reporter,
            run_plugin_store_job,
        )

        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        ref = (body.ref or "main").strip() or "main"
        if not (body.ref or "").strip():
            index = await load_community_plugin_index_safe()
            for entry in index.get("plugins") or []:
                if str(entry.get("plugin_id")) == body.plugin_id.strip():
                    ref = str(entry.get("ref") or ref).strip() or "main"
                    break
        job = await create_plugin_store_job(
            kind="community",
            target=body.plugin_id.strip(),
            action="update",
        )

        async def runner(j) -> None:
            data = await update_community_plugin_with_options(
                j.target,
                ref=ref,
                restart=bool(body.restart),
                on_progress=job_progress_reporter(j),
            )
            drop_read_cache(("plugins-community-store", "plugins"))
            j.result = dict(data)
            j.message = str(data.get("message") or "完成")

        asyncio.create_task(run_plugin_store_job(job, runner))
        return JSONResponse({"ok": True, "data": {"job_id": job.job_id, "package": job.target}})

    @router.post(f"{x}/plugins/community-plugins/uninstall-async", include_in_schema=True)
    async def _plugins_community_plugins_uninstall_async(
        body: CommunityPluginActionBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        import asyncio

        from pallas.console.cli.community_plugin_ops import uninstall_community_plugin_with_options
        from pallas.console.webui.plugin_store_job_progress import (
            create_plugin_store_job,
            job_progress_reporter,
            run_plugin_store_job,
        )

        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        job = await create_plugin_store_job(
            kind="community",
            target=body.plugin_id.strip(),
            action="uninstall",
        )

        async def runner(j) -> None:
            data = await uninstall_community_plugin_with_options(
                j.target,
                restart=bool(body.restart),
                on_progress=job_progress_reporter(j),
            )
            drop_read_cache(("plugins-community-store", "plugins"))
            j.result = dict(data)
            j.message = str(data.get("message") or "完成")

        asyncio.create_task(run_plugin_store_job(job, runner))
        return JSONResponse({"ok": True, "data": {"job_id": job.job_id, "package": job.target}})

    @router.post(f"{x}/plugins/community-plugins/uninstall", include_in_schema=True)
    async def _plugins_community_plugins_uninstall(
        body: CommunityPluginActionBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.cli.community_plugin_ops import (
            CommunityPluginInstallError,
            uninstall_community_plugin_with_options,
        )
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        try:
            data = await uninstall_community_plugin_with_options(
                body.plugin_id,
                restart=bool(body.restart),
            )
            drop_read_cache(("plugins-community-store", "plugins"))
            return JSONResponse({"ok": True, "data": data})
        except CommunityPluginInstallError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 卸载社区插件失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.post(f"{x}/plugins/community-plugins/update", include_in_schema=True)
    async def _plugins_community_plugins_update(
        body: CommunityPluginActionBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.cli.community_plugin_ops import (
            CommunityPluginInstallError,
            update_community_plugin_with_options,
        )
        from pallas.console.webui.community_plugin_index import load_community_plugin_index_safe
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        ref = (body.ref or "main").strip() or "main"
        if not (body.ref or "").strip():
            index = await load_community_plugin_index_safe()
            for entry in index.get("plugins") or []:
                if str(entry.get("plugin_id")) == body.plugin_id.strip():
                    ref = str(entry.get("ref") or ref).strip() or "main"
                    break
        try:
            data = await update_community_plugin_with_options(
                body.plugin_id,
                ref=ref,
                restart=bool(body.restart),
            )
            drop_read_cache(("plugins-community-store", "plugins"))
            return JSONResponse({"ok": True, "data": data})
        except CommunityPluginInstallError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 更新社区插件失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    from pallas.console.webui.git_mirror_api import register_git_mirror_router

    register_git_mirror_router(
        router,
        x=x,
        check_write_token=lambda *, x_pallas_token=None, token=None: check_pallas_write_token(
            plugin_config,
            x_pallas_token=x_pallas_token,
            token=token,
        ),
    )

    @router.get(f"{x}/plugins/help-menu-visibility", include_in_schema=True)
    async def _plugins_help_menu_visibility() -> JSONResponse:
        try:
            from packages.help.visibility import load_help_hidden_plugins, resolve_help_ignored_plugins

            data = {
                "hidden_plugins": load_help_hidden_plugins(),
                "ignored_plugins": resolve_help_ignored_plugins(),
            }
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/plugins/help-menu-visibility", include_in_schema=True)
    async def _plugins_help_menu_visibility_put(
        body: HelpMenuVisibilityBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            from packages.help.visibility import save_help_hidden_plugins

            hidden = save_help_hidden_plugins(body.hidden_plugins)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        drop_read_cache(("plugins", "home-overview"))
        return JSONResponse({"ok": True, "data": {"hidden_plugins": hidden}})

    @router.get(f"{x}/plugins/global-disable", include_in_schema=True)
    async def _plugins_global_disable_get() -> JSONResponse:
        try:
            from packages.help.global_disable import (
                GLOBAL_DISABLE_PROTECTED_PLUGINS,
                load_global_disabled_plugins,
            )

            data = {
                "disabled_plugins": load_global_disabled_plugins(),
                "protected_plugins": sorted(GLOBAL_DISABLE_PROTECTED_PLUGINS),
            }
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/plugins/global-disable", include_in_schema=True)
    async def _plugins_global_disable_put(
        body: GlobalPluginDisableBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            from packages.help.global_disable import (
                GLOBAL_DISABLE_PROTECTED_PLUGINS,
                save_global_disabled_plugins,
            )
            from packages.help.plugin_manager import invalidate_disabled_plugin_gate_cache

            disabled = save_global_disabled_plugins(body.disabled_plugins)
            await invalidate_disabled_plugin_gate_cache(clear_all=True)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        drop_read_cache(("plugins", "home-overview"))
        return JSONResponse({
            "ok": True,
            "data": {
                "disabled_plugins": disabled,
                "protected_plugins": sorted(GLOBAL_DISABLE_PROTECTED_PLUGINS),
            },
        })

    @router.get(f"{x}/plugins/group-fleet-whitelist", include_in_schema=True)
    async def _plugins_group_fleet_whitelist_get() -> JSONResponse:
        try:
            from packages.help.global_disable import GLOBAL_DISABLE_PROTECTED_PLUGINS
            from packages.help.group_fleet_whitelist import load_group_fleet_whitelist

            data = {
                "entries": load_group_fleet_whitelist(),
                "protected_plugins": sorted(GLOBAL_DISABLE_PROTECTED_PLUGINS),
            }
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/plugins/group-fleet-whitelist", include_in_schema=True)
    async def _plugins_group_fleet_whitelist_put(
        body: GroupFleetWhitelistBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            from packages.help.global_disable import GLOBAL_DISABLE_PROTECTED_PLUGINS
            from packages.help.group_fleet_whitelist import save_group_fleet_whitelist
            from packages.help.plugin_manager import invalidate_disabled_plugin_gate_cache

            entries = save_group_fleet_whitelist([
                {"group_id": item.group_id, "plugins": item.plugins} for item in body.entries
            ])
            await invalidate_disabled_plugin_gate_cache(clear_all=True)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        drop_read_cache(("plugins", "home-overview"))
        return JSONResponse({
            "ok": True,
            "data": {
                "entries": entries,
                "protected_plugins": sorted(GLOBAL_DISABLE_PROTECTED_PLUGINS),
            },
        })

    @router.get(
        f"{x}/plugins/{{plugin_name}}/config",
        include_in_schema=True,
        response_model=_ApiOkResponse[_PluginConfigData],
    )
    async def _plugin_config_get(plugin_name: str) -> dict[str, Any]:
        try:
            data = plugin_config_payload(plugin_name)
        except ValueError:
            # 无 config.py 或配置模型不可用时返回空配置，前端以“不可编辑”展示
            data = {"plugin": plugin_name, "module": "", "fields": [], "unexpected_keys": []}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"ok": True, "data": data}

    @router.get(
        f"{x}/plugins/{{plugin_name}}/config/raw",
        include_in_schema=True,
        response_model=_ApiOkResponse[_PluginConfigRawData],
    )
    async def _plugin_config_raw_get(plugin_name: str) -> dict[str, Any]:
        from pallas.console.webui.plugin_api import plugin_config_raw_toml

        try:
            text = plugin_config_raw_toml(plugin_name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "data": {"toml": text}}

    @router.put(
        f"{x}/plugins/{{plugin_name}}/config/raw",
        include_in_schema=True,
        response_model=_ApiOkResponse[_PluginConfigData],
    )
    async def _plugin_config_raw_put(
        plugin_name: str,
        body: PluginConfigRawBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> dict[str, Any]:
        from pallas.console.webui.plugin_api import apply_plugin_config_raw_toml

        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            data = apply_plugin_config_raw_toml(plugin_name, str(body.toml or ""))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "data": data}

    @router.put(
        f"{x}/plugins/{{plugin_name}}/config",
        include_in_schema=True,
        response_model=_ApiOkResponse[_PluginConfigData],
    )
    async def _plugin_config_put(
        plugin_name: str,
        body: PluginConfigUpdateBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            data = apply_plugin_config_patch(plugin_name, dict(body.values or {}))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            from pydantic import ValidationError

            if isinstance(e, ValidationError):
                from pallas.console.webui.plugin_api import format_validation_error

                raise HTTPException(status_code=400, detail=format_validation_error(e)) from e
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/plugins/{{plugin_name}}/config-check", include_in_schema=True)
    async def _plugin_config_check(
        plugin_name: str,
        body: PluginConfigUpdateBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if plugin_name != "draw":
            raise HTTPException(status_code=400, detail="该插件暂不支持配置检测")
        from pallas.core.shared.service_probe.format import format_probe_lines
        from pallas.product.service_gateways.media_probe import probe_image_gateways

        draft = dict(body.values or {})
        results = await probe_image_gateways(draft_values=draft)
        lines = format_probe_lines(results)
        return JSONResponse(
            {
                "ok": True,
                "data": {
                    "lines": lines,
                    "results": [r.to_dict() for r in results],
                },
            },
        )
