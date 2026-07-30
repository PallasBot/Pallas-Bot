"""Pallas-Bot WebUI console API: update routes."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from nonebot import logger

from .console_read_cache import cached_read, drop_read_cache
from .extended_common import check_pallas_write_token

if TYPE_CHECKING:
    from .config import Config


async def warm_console_read_caches() -> None:
    """启动后后台预热首屏慢读接口的进程内缓存。"""
    fn = _warm_console_read_caches_fn
    if fn is not None:
        await fn()


async def _load_webui_update_check_payload(plugin_config: Config) -> dict[str, Any]:
    from pallas.core.shared.utils.format_exception import format_exception_for_log
    from pallas.core.shared.utils.github_release import fetch_release_notes_range, release_tags_equivalent

    from .manager import fetch_latest_webui_release, get_installed_webui_version

    repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "PallasBot/Pallas-Bot")
    asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "dist.zip")
    github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
    installed = get_installed_webui_version()
    current_tag = str(installed.get("tag", "") or "").strip()
    try:
        latest = await fetch_latest_webui_release(repo, token=github_token, asset_name=asset)
        latest_tag = str(latest.get("tag", "") or "").strip()
        release_url = str(latest.get("html_url", "") or "").strip()
        asset_url = str(latest.get("asset_url", "") or "").strip()
    except Exception as e:  # noqa: BLE001
        err_msg = format_exception_for_log(e)
        logger.warning("Pallas-Bot 控制台: WebUI 更新检查失败（GitHub），repo={} err={}", repo, err_msg)
        return {
            "current_tag": current_tag,
            "latest_tag": None,
            "has_update": False,
            "release_url": "",
            "asset_url": "",
            "release_notes": "",
            "error": err_msg,
            "checked_at": time.time(),
        }
    has_update = bool(latest_tag and not release_tags_equivalent(current_tag, latest_tag))
    # dist 资产可能来自主仓 Release，产品变更史写在 WebUI 仓 CHANGELOG
    changelog_url = "https://github.com/PallasBot/Pallas-Bot-WebUI/blob/main/CHANGELOG.md"
    release_notes = await fetch_release_notes_range(
        repo,
        current_tag=current_tag,
        latest_tag=latest_tag,
        token=github_token,
        user_agent="Pallas-Bot-PallasWebUI/1.0",
        changelog_url=changelog_url,
    )
    if not release_notes:
        notes_raw = str(latest.get("body", "") or "").strip()
        notes_max = 12000
        release_notes = (
            notes_raw
            if len(notes_raw) <= notes_max
            else f"{notes_raw[:notes_max].rstrip()}\n\n…（已截断，完整内容见 Release 页面）"
        )
    return {
        "current_tag": current_tag,
        "latest_tag": latest_tag,
        "has_update": has_update,
        "release_url": release_url,
        "asset_url": asset_url,
        "release_notes": release_notes,
        "error": None,
        "checked_at": time.time(),
    }


def _bot_restart_available() -> bool:
    from pallas.console.cli.bot_process import bot_lifecycle_available

    return bot_lifecycle_available()


async def _load_bot_update_check_payload(plugin_config: Config) -> dict[str, Any]:
    from pallas.core.shared.utils.format_exception import format_exception_for_log
    from pallas.core.shared.utils.github_release import fetch_release_notes_range

    from .manager import (
        bot_has_release_update,
        bot_is_development_build,
        fetch_latest_bot_release,
        get_bot_current_version,
        inspect_bot_deployment,
    )

    github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
    current = get_bot_current_version()
    current_tag = current.get("tag", "")
    current_commit = current.get("commit", "")
    bot_repo = "PallasBot/Pallas-Bot"
    try:
        latest = await fetch_latest_bot_release(bot_repo, token=github_token)
        latest_tag = str(latest.get("tag", "") or "").strip()
        release_url = str(latest.get("html_url", "") or "").strip()
    except Exception as e:  # noqa: BLE001
        err_msg = format_exception_for_log(e)
        logger.warning("Pallas-Bot 控制台: Bot 版本更新检查失败（GitHub） err={}", err_msg)
        return {
            "current_tag": current_tag,
            "current_commit": current_commit,
            "latest_tag": None,
            "has_update": False,
            "development_build": False,
            "release_url": "",
            "release_notes": "",
            "error": err_msg,
            "checked_at": time.time(),
            **inspect_bot_deployment(),
            "restart_available": _bot_restart_available(),
        }
    has_update = bot_has_release_update(
        latest_tag=latest_tag,
        current_tag=str(current_tag or ""),
        current_commit=str(current_commit or ""),
    )
    development_build = bot_is_development_build(
        latest_tag=latest_tag,
        current_tag=str(current_tag or ""),
        current_commit=str(current_commit or ""),
    )
    release_notes = await fetch_release_notes_range(
        bot_repo,
        current_tag=str(current_tag or ""),
        latest_tag=latest_tag,
        token=github_token,
        user_agent="Pallas-Bot/1.0",
        changelog_url="",
    )
    if not release_notes:
        notes_raw = str(latest.get("body", "") or "").strip()
        notes_max = 12000
        release_notes = (
            notes_raw
            if len(notes_raw) <= notes_max
            else f"{notes_raw[:notes_max].rstrip()}\n\n…（已截断，完整内容见 Release 页面）"
        )
    return {
        "current_tag": current_tag,
        "current_commit": current_commit,
        "latest_tag": latest_tag,
        "has_update": has_update,
        "development_build": development_build,
        "release_url": release_url,
        "release_notes": release_notes,
        "error": None,
        "checked_at": time.time(),
        **inspect_bot_deployment(),
        "restart_available": _bot_restart_available(),
    }


_warm_console_read_caches_fn = None


def set_warm_console_read_caches_impl(fn) -> None:
    global _warm_console_read_caches_fn
    _warm_console_read_caches_fn = fn


def register_update_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
) -> None:
    """Register update routes and wire warm cache impl."""

    @router.get(f"{x}/update/check", include_in_schema=True)
    async def _update_check() -> JSONResponse:
        repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "PallasBot/Pallas-Bot")
        asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "dist.zip")
        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        cache_key = f"update_check_webui:{repo}:{asset}:{bool(github_token)}"

        async def _load() -> dict[str, Any]:
            return await _load_webui_update_check_payload(plugin_config)

        data = await cached_read(key=cache_key, loader=_load, ttl_sec=120.0, stale_sec=900.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/update/bot/check", include_in_schema=True)
    async def _bot_update_check() -> JSONResponse:
        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        cache_key = f"update_check_bot:{bool(github_token)}"

        async def _load() -> dict[str, Any]:
            return await _load_bot_update_check_payload(plugin_config)

        data = await cached_read(key=cache_key, loader=_load, ttl_sec=120.0, stale_sec=900.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/update/check-all", include_in_schema=True)
    async def _update_check_all() -> JSONResponse:
        """一次返回 WebUI 与 Bot 更新检查结果（GS 控制台同款聚合接口）。"""
        repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "PallasBot/Pallas-Bot")
        asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "dist.zip")
        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        webui_key = f"update_check_webui:{repo}:{asset}:{bool(github_token)}"
        bot_key = f"update_check_bot:{bool(github_token)}"

        async def load_webui() -> dict[str, Any]:
            return await _load_webui_update_check_payload(plugin_config)

        async def load_bot() -> dict[str, Any]:
            return await _load_bot_update_check_payload(plugin_config)

        webui_data, bot_data = await asyncio.gather(
            cached_read(key=webui_key, loader=load_webui, ttl_sec=120.0, stale_sec=900.0),
            cached_read(key=bot_key, loader=load_bot, ttl_sec=120.0, stale_sec=900.0),
        )
        checked_at = (
            max(
                float(webui_data.get("checked_at") or 0),
                float(bot_data.get("checked_at") or 0),
            )
            or time.time()
        )
        return JSONResponse({
            "ok": True,
            "data": {
                "webui": webui_data,
                "bot": bot_data,
                "checked_at": checked_at,
            },
        })

    @router.get(f"{x}/update/changelog", include_in_schema=True)
    async def _update_changelog(
        target: str = Query(..., description="webui 或 bot"),
        max_versions: int = Query(default=10, ge=1, le=30),
    ) -> JSONResponse:
        """拉取仓库 CHANGELOG.md，截取最近若干版本段（与发行说明分离）。"""
        from pallas.core.shared.utils.changelog_md import load_update_changelog_payload
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        try:
            data = await load_update_changelog_payload(target, max_versions=max_versions)
            return JSONResponse({"ok": True, "data": data})
        except Exception as e:  # noqa: BLE001
            return JSONResponse(
                {
                    "ok": False,
                    "error": format_exception_for_log(e),
                    "data": {
                        "target": str(target or "").strip().lower() or None,
                        "markdown": "",
                        "changelog_url": "",
                    },
                },
                status_code=502,
            )

    @router.get(f"{x}/update/bot/config-migration/check", include_in_schema=True)
    async def _bot_config_migration_check() -> JSONResponse:
        from pallas.core.foundation.config.migrate_env_to_pallas import inspect_env_to_pallas_migration

        return JSONResponse({"ok": True, "data": inspect_env_to_pallas_migration()})

    @router.post(f"{x}/update/bot/config-migration/apply", include_in_schema=True)
    async def _bot_config_migration_apply(
        force: bool = Query(default=False),
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.core.foundation.config.migrate_env_to_pallas import (
            EnvToPallasMigrationError,
            apply_env_to_pallas_migration,
            inspect_env_to_pallas_migration,
        )
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        try:
            result = apply_env_to_pallas_migration(force=force)
            data = result.as_dict()
            data["migration"] = inspect_env_to_pallas_migration()
            return JSONResponse({"ok": True, "data": data})
        except EnvToPallasMigrationError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: .env 配置迁移失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.post(f"{x}/update/bot/apply", include_in_schema=True)
    async def _bot_update_apply(
        restart: bool = Query(default=False),
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from packages.pb_webui.manager import BotGitUpdateError
        from pallas.console.cli.update_ops import apply_bot_update
        from pallas.console.webui.update_apply_progress import (
            create_update_apply_job,
            run_update_apply_job,
        )
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        job = await create_update_apply_job("bot", restart=restart)
        logger.info(
            "Pallas-Bot 控制台: Bot 仓库在线更新（git）任务已排队 job_id={} restart={}",
            job.job_id,
            restart,
        )

        async def _runner(j: Any) -> None:
            def on_progress(pct: int, message: str) -> None:
                j.push("running", message, progress_percent=pct)

            try:
                data = await apply_bot_update(
                    github_token=github_token,
                    repo="PallasBot/Pallas-Bot",
                    restart=restart,
                    on_progress=on_progress,
                )
                drop_read_cache(("update_check_bot:",))
                j.result = data
                j.message = str(data.get("message") or "完成")
            except BotGitUpdateError as e:
                j.push("failed", error=e.detail, progress_percent=j.progress_percent)
            except Exception as e:  # noqa: BLE001
                logger.exception("Pallas-Bot 控制台: Bot 仓库更新失败")
                j.push("failed", error=format_exception_for_log(e), progress_percent=j.progress_percent)

        asyncio.create_task(run_update_apply_job(job, _runner))
        return JSONResponse({"ok": True, "data": {"job_id": job.job_id, "kind": "bot", "restart": restart}})

    @router.post(f"{x}/update/apply", include_in_schema=True)
    async def _update_apply(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.cli.update_ops import WebuiUpdateError, apply_webui_dist_update
        from pallas.console.webui.update_apply_progress import (
            create_update_apply_job,
            run_update_apply_job,
        )
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "PallasBot/Pallas-Bot")
        asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "dist.zip")
        tag = str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or "")
        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        job = await create_update_apply_job("webui")

        async def _runner(j: Any) -> None:
            def on_progress(pct: int, message: str) -> None:
                j.push("running", message, progress_percent=pct)

            try:
                data = await apply_webui_dist_update(
                    repo=repo,
                    asset=asset,
                    tag=tag,
                    github_token=github_token,
                    refresh_runtime_meta=True,
                    on_progress=on_progress,
                )
                drop_read_cache(("update_check_webui:",))
                j.result = data
                j.message = str(data.get("message") or "更新成功")
            except WebuiUpdateError as e:
                j.push("failed", error=e.detail, progress_percent=j.progress_percent)
            except Exception as e:  # noqa: BLE001
                logger.exception("Pallas-Bot 控制台: WebUI 更新失败")
                j.push("failed", error=format_exception_for_log(e), progress_percent=j.progress_percent)

        asyncio.create_task(run_update_apply_job(job, _runner))
        return JSONResponse({"ok": True, "data": {"job_id": job.job_id, "kind": "webui"}})

    @router.get(f"{x}/update/auto/status", include_in_schema=True)
    async def _update_auto_status() -> JSONResponse:
        from .webui_auto_update import auto_update_status_payload

        return JSONResponse({"ok": True, "data": auto_update_status_payload(plugin_config)})

    @router.post(f"{x}/update/auto/ack", include_in_schema=True)
    async def _update_auto_ack(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from .webui_auto_update import ack_pending_notice, auto_update_status_payload

        ack_pending_notice()
        return JSONResponse({"ok": True, "data": auto_update_status_payload(plugin_config)})

    @router.post(f"{x}/update/auto/run-once", include_in_schema=True)
    async def _update_auto_run_once(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from .webui_auto_update import auto_update_status_payload, run_auto_update_tick

        tick = await run_auto_update_tick(config=plugin_config, force=True)
        data = auto_update_status_payload(plugin_config)
        data["tick"] = tick
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/update/jobs/{{job_id}}", include_in_schema=True)
    async def _update_apply_job_get(job_id: str) -> JSONResponse:
        from pallas.console.webui.update_apply_progress import get_update_apply_job

        job = get_update_apply_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job_not_found")
        return JSONResponse({"ok": True, "data": job.as_dict()})

    @router.get(f"{x}/update/jobs/{{job_id}}/stream", include_in_schema=True)
    async def _update_apply_job_stream(job_id: str) -> StreamingResponse:
        from pallas.console.webui.update_apply_progress import iter_update_apply_job_sse

        return StreamingResponse(
            iter_update_apply_job_sse(job_id.strip()),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def _warm_console_read_caches_impl() -> None:
        from pallas.product.community_stats.public_stats import fetch_community_public_stats

        repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "PallasBot/Pallas-Bot")
        asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "dist.zip")
        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        webui_key = f"update_check_webui:{repo}:{asset}:{bool(github_token)}"
        bot_key = f"update_check_bot:{bool(github_token)}"

        async def warm(key: str, loader, ttl: float, stale: float) -> None:
            try:
                await cached_read(key=key, loader=loader, ttl_sec=ttl, stale_sec=stale)
            except Exception as e:  # noqa: BLE001
                logger.debug("Pallas-Bot 控制台: 预热读缓存失败 key={} err={}", key, e)

        async def load_webui() -> dict[str, Any]:
            return await _load_webui_update_check_payload(plugin_config)

        async def load_bot() -> dict[str, Any]:
            return await _load_bot_update_check_payload(plugin_config)

        async def load_community() -> dict[str, Any]:
            return await fetch_community_public_stats()

        await asyncio.gather(
            warm(webui_key, load_webui, 120.0, 900.0),
            warm(bot_key, load_bot, 120.0, 900.0),
            warm("community-stats", load_community, 30.0, 120.0),
        )

    global _warm_console_read_caches_fn
    _warm_console_read_caches_fn = _warm_console_read_caches_impl

    set_warm_console_read_caches_impl(_warm_console_read_caches_impl)
