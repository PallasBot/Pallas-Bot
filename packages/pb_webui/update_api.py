"""Pallas-Bot WebUI console API: update routes."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from nonebot import logger
from pydantic import BaseModel, ConfigDict, Field

from .console_read_cache import cached_read, drop_read_cache
from .extended_common import check_pallas_write_token
from .manager import DEFAULT_WEBUI_DIST_ZIP_REPO

if TYPE_CHECKING:
    from .config import Config


class BotGitApplyBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: str = Field(default="release", description="release 或 commit")
    branch: str = Field(default="", description="commit 模式跟踪分支")
    ref: str = Field(default="", description="目标 tag 或 commit；空表示 tip/latest")
    strategy: str = Field(default="safe", description="safe 或 force")
    restart: bool = Field(default=False, description="更新后安排 Bot 重启")


async def warm_console_read_caches() -> None:
    """启动后后台预热首屏慢读接口的进程内缓存。"""
    fn = _warm_console_read_caches_fn
    if fn is not None:
        await fn()


async def _load_webui_update_check_payload(plugin_config: Config) -> dict[str, Any]:
    from pallas.core.shared.utils.format_exception import format_exception_for_log
    from pallas.core.shared.utils.github_release import fetch_release_notes_range

    from .manager import (
        DEFAULT_WEBUI_DIST_ZIP_ASSET,
        DEFAULT_WEBUI_DIST_ZIP_REPO,
        get_installed_webui_version,
        normalize_webui_dist_zip_repo,
        resolve_compatible_webui_release,
        webui_has_release_update,
    )

    repo = normalize_webui_dist_zip_repo(
        str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or DEFAULT_WEBUI_DIST_ZIP_REPO),
    )
    asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or DEFAULT_WEBUI_DIST_ZIP_ASSET)
    requested_tag = str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or "").strip()
    github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
    installed = get_installed_webui_version()
    current_tag = str(installed.get("tag", "") or "").strip()
    try:
        selected = await resolve_compatible_webui_release(
            repo,
            asset,
            requested_tag,
            token=github_token,
        )
        latest_tag = str(selected.get("tag", "") or "").strip()
        release_url = str(selected.get("html_url", "") or "").strip()
        asset_url = str(selected.get("asset_url", "") or "").strip()
    except Exception as e:  # noqa: BLE001
        err_msg = format_exception_for_log(e)
        logger.warning("[WebUI] WebUI update check failed for repository [{}]: [{}]", repo, err_msg)
        return {
            "current_tag": current_tag,
            "latest_tag": None,
            "has_update": False,
            "release_url": "",
            "asset_url": "",
            "release_notes": "",
            "error": err_msg,
            "compatibility": {"status": "unavailable", "reason": err_msg},
            "requested_tag": requested_tag or None,
            "checked_at": time.time(),
        }
    has_update = webui_has_release_update(latest_tag=latest_tag, current_tag=current_tag)
    # 资产与兼容清单来自 WebUI Release，产品变更史写在 WebUI 仓 CHANGELOG
    changelog_url = "https://github.com/PallasBot/Pallas-Bot-WebUI/blob/main/CHANGELOG.md"
    release_notes = await fetch_release_notes_range(
        repo,
        current_tag=current_tag,
        latest_tag=latest_tag,
        token=github_token,
        user_agent="Pallas-Bot-PallasWebUI/1.0",
        limit=None,
        changelog_url=changelog_url,
        mirror_scope="webui",
    )
    if not release_notes:
        notes_raw = str(selected.get("body", "") or "").strip()
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
        "compatibility": {
            "status": "compatible",
            "bot_commit": str(selected.get("bot_commit", "") or "").strip(),
            "min_bot_commit": str(selected.get("min_bot_commit", "") or "").strip(),
        },
        "bot_commit": str(selected.get("bot_commit", "") or "").strip(),
        "min_bot_commit": str(selected.get("min_bot_commit", "") or "").strip(),
        "requested_tag": requested_tag or None,
        "checked_at": time.time(),
    }


def _webui_update_cache_key(plugin_config: Config) -> str:
    from .manager import (
        DEFAULT_WEBUI_DIST_ZIP_ASSET,
        DEFAULT_WEBUI_DIST_ZIP_REPO,
        get_bot_current_commit,
        normalize_webui_dist_zip_repo,
    )

    repo = normalize_webui_dist_zip_repo(
        str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or DEFAULT_WEBUI_DIST_ZIP_REPO),
    )
    asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or DEFAULT_WEBUI_DIST_ZIP_ASSET)
    tag = str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or "").strip()
    token = bool(str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip())
    commit = get_bot_current_commit() or "unknown"
    return f"update_check_webui:{repo}:{asset}:{tag}:{commit}:{token}"


def _bot_restart_available() -> bool:
    from pallas.console.cli.bot_process import bot_lifecycle_available

    return bot_lifecycle_available()


async def _load_bot_update_check_payload(plugin_config: Config) -> dict[str, Any]:
    from pallas.core.shared.utils.format_exception import format_exception_for_log
    from pallas.core.shared.utils.github_release import fetch_release_notes_range

    from .bot_git_manage import normalize_bot_git_track_branch
    from .manager import (
        BotGitUpdateError,
        bot_branch_update_probe,
        bot_has_release_update,
        bot_is_development_build,
        fetch_bot_origin_refs,
        fetch_latest_bot_release,
        get_bot_current_version,
        inspect_bot_deployment,
        normalize_bot_update_track,
    )

    github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
    update_track = normalize_bot_update_track(getattr(plugin_config, "pallas_bot_update_track", "release"))
    preferred_branch = normalize_bot_git_track_branch(getattr(plugin_config, "pallas_bot_update_branch", "") or "")
    current = get_bot_current_version()
    bot_repo = "PallasBot/Pallas-Bot"
    deploy = inspect_bot_deployment()
    current_tag = current.get("tag", "")
    current_commit = current.get("commit", "")
    if deploy.get("deployment_mode") == "docker":
        current_tag = str(deploy.get("runtime_version") or deploy.get("image_version") or current_tag)
    base = {
        "current_tag": current_tag,
        "current_commit": current_commit,
        "update_track": update_track,
        "update_branch": preferred_branch,
        "upstream_ref": "",
        "latest_commit": "",
        "commits_behind": 0,
        "checked_at": time.time(),
        **deploy,
        "restart_available": _bot_restart_available(),
    }

    latest_tag = ""
    release_url = ""
    release_notes = ""
    github_err: str | None = None
    try:
        latest = await fetch_latest_bot_release(bot_repo, token=github_token)
        latest_tag = str(latest.get("tag", "") or "").strip()
        release_url = str(latest.get("html_url", "") or "").strip()
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
    except Exception as e:  # noqa: BLE001
        github_err = format_exception_for_log(e)
        logger.warning("[WebUI] Bot release update check failed: [{}]", github_err)

    if update_track == "branch":
        if not deploy.get("git_available"):
            return {
                **base,
                "latest_tag": latest_tag or None,
                "has_update": False,
                "development_build": False,
                "release_url": release_url,
                "release_notes": release_notes,
                "error": "当前不是 git 工作副本，无法使用分支轨道",
            }
        fetch_err: str | None = None
        try:
            await fetch_bot_origin_refs()
        except BotGitUpdateError as e:
            fetch_err = e.detail
            logger.warning("[WebUI] Bot branch update fetch failed: [{}]", fetch_err)
        except Exception as e:  # noqa: BLE001
            fetch_err = format_exception_for_log(e)
            logger.warning("[WebUI] Bot branch update fetch raised an exception: [{}]", fetch_err)
        probe = bot_branch_update_probe(preferred_branch=preferred_branch)
        err = probe.get("error") or fetch_err or github_err
        # fetch 失败但本地仍有远端 refs 时，仍可给出 has_update；否则透传错误
        has_branch_update = bool(probe.get("has_update")) if not probe.get("error") else False
        return {
            **base,
            "latest_tag": latest_tag or None,
            "has_update": has_branch_update,
            "development_build": False,
            "upstream_ref": str(probe.get("upstream_ref") or ""),
            "latest_commit": str(probe.get("latest_commit") or ""),
            "commits_behind": int(probe.get("commits_behind") or 0),
            "release_url": release_url,
            "release_notes": release_notes,
            "error": err if not has_branch_update else None,
        }

    if github_err and not latest_tag:
        return {
            **base,
            "latest_tag": None,
            "has_update": False,
            "development_build": False,
            "release_url": "",
            "release_notes": "",
            "error": github_err,
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
    return {
        **base,
        "latest_tag": latest_tag,
        "has_update": has_update,
        "development_build": development_build,
        "release_url": release_url,
        "release_notes": release_notes,
        "error": None,
    }


_warm_console_read_caches_fn = None

# 进程级共享的外部请求信号量：所有「打外部」的 warm loader 在访问外部前统一经它，
# 保证同刻最多 2 个外部请求，避免冷启动风暴三路并发打外部 GitHub/社区接口。
_EXTERNAL_SEM = asyncio.Semaphore(2)

# 外部批相对本地批的延后秒数，给首屏本地缓存先建好、避免与首屏 HTTP 抢事件循环。
_STAGGER_EXTERNAL_WARM_SEC = 1.0

# 本地批 warm 键：全走 asyncio.to_thread / 内存，不打外部。
_LOCAL_WARM_KEYS = (
    "instances",
    "plugins",
    "message-stats:all",
    "plugin-run-stats:all:logsrc:all:tbl:0:view:full",
    "bots",
    "system",
)
_COMMUNITY_STATS_WARM_KEY = "community-stats"


def _batch_warm_keys(webui_key: str, bot_key: str) -> tuple[list[str], list[str]]:
    """把首屏预热 warm 键拆成 (本地批, 外部批)，便于测试与顺序控制。"""
    local_keys = list(_LOCAL_WARM_KEYS)
    external_keys = [webui_key, bot_key, _COMMUNITY_STATS_WARM_KEY]
    return local_keys, external_keys


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
        cache_key = _webui_update_cache_key(plugin_config)

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
        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        webui_key = _webui_update_cache_key(plugin_config)
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
            logger.exception("[WebUI] .env 配置迁移失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.get(f"{x}/update/git/bot/status", include_in_schema=True)
    async def _bot_git_status() -> JSONResponse:
        from .bot_git_manage import build_bot_git_status_payload
        from .manager import normalize_bot_update_track

        update_track = normalize_bot_update_track(getattr(plugin_config, "pallas_bot_update_track", "release"))
        update_branch = str(getattr(plugin_config, "pallas_bot_update_branch", "") or "").strip()
        data = await build_bot_git_status_payload(
            update_track=update_track,
            update_branch=update_branch,
            fetch=True,
            restart_available=_bot_restart_available(),
        )
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/update/git/bot/history", include_in_schema=True)
    async def _bot_git_history(
        mode: str = Query(default="commit", description="commit 或 release"),
        branch: str = Query(default="", description="commit 模式分支名"),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> JSONResponse:
        from .bot_git_manage import load_bot_git_history_payload

        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        data = await load_bot_git_history_payload(
            mode=mode,
            branch=branch,
            limit=limit,
            fetch=True,
            github_token=github_token,
        )
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/update/git/bot/apply", include_in_schema=True)
    async def _bot_git_apply(
        body: BotGitApplyBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from packages.pb_webui.manager import BotGitUpdateError
        from pallas.console.cli.bot_process import bot_lifecycle_available, schedule_bot_restart
        from pallas.console.cli.update_ops import apply_docker_bot_release, validate_docker_bot_update
        from pallas.console.webui.update_apply_progress import (
            create_update_apply_job,
            run_update_apply_job,
        )
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        from .bot_git_manage import apply_bot_git_target, normalize_git_apply_mode, normalize_git_apply_strategy
        from .manager import inspect_bot_deployment

        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        apply_mode = normalize_git_apply_mode(body.mode)
        apply_strategy = normalize_git_apply_strategy(body.strategy)
        branch = (body.branch or "").strip()
        target_ref = (body.ref or "").strip()
        restart = bool(body.restart)

        job = await create_update_apply_job("bot", restart=restart)
        logger.info(
            "[WebUI] Bot git update job [{}] queued with mode [{}], strategy [{}], reference [{}], restart [{}]",
            job.job_id,
            apply_mode,
            apply_strategy,
            target_ref or "(tip/latest)",
            restart,
        )

        async def _runner(j: Any) -> None:
            def on_progress(pct: int, message: str) -> None:
                j.push("running", message, progress_percent=pct)

            try:
                deployment = inspect_bot_deployment()
                if validate_docker_bot_update(deployment, mode=apply_mode, strategy=apply_strategy):
                    result = await apply_docker_bot_release(
                        github_token=github_token,
                        repo="PallasBot/Pallas-Bot",
                        target_tag=target_ref,
                        on_progress=on_progress,
                    )
                else:
                    result = await apply_bot_git_target(
                        github_token=github_token,
                        repo="PallasBot/Pallas-Bot",
                        mode=apply_mode,
                        preferred_branch=branch,
                        target_ref=target_ref,
                        strategy=apply_strategy,
                        on_progress=on_progress,
                    )
                scheduled = False
                if restart and bot_lifecycle_available():
                    on_progress(96, "安排进程重启…")
                    scheduled = schedule_bot_restart(delay_s=3.0)
                out = dict(result)
                out["restart_scheduled"] = scheduled
                logger.info(
                    "[WebUI] Bot 更新成功，mode [{}]、strategy [{}]、tag [{}]、restart_scheduled [{}]",
                    apply_mode,
                    apply_strategy,
                    str(out.get("tag") or ""),
                    scheduled,
                )
                if restart:
                    base = str(out.get("message") or "").rstrip()
                    note = "已安排 Bot 重启。" if scheduled else "未能安排自动重启，请手动重启 Bot。"
                    out["message"] = f"{base} {note}".strip() if base else note
                drop_read_cache(("update_check_bot:",))
                j.result = out
                j.message = str(out.get("message") or "完成")
                on_progress(100, j.message)
            except BotGitUpdateError as e:
                logger.warning("[WebUI] Bot 更新业务失败: {}", e.detail)
                j.push("failed", error=e.detail, progress_percent=j.progress_percent)
            except Exception as e:  # noqa: BLE001
                logger.exception("[WebUI] Bot git 定向更新失败")
                j.push("failed", error=format_exception_for_log(e), progress_percent=j.progress_percent)

        asyncio.create_task(run_update_apply_job(job, _runner))
        return JSONResponse({
            "ok": True,
            "data": {
                "job_id": job.job_id,
                "kind": "bot",
                "mode": apply_mode,
                "strategy": apply_strategy,
                "restart": restart,
            },
        })

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
            "[WebUI] Bot repository update job [{}] queued with restart [{}]",
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
                logger.exception("[WebUI] Bot 仓库更新失败")
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

        repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or DEFAULT_WEBUI_DIST_ZIP_REPO)
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
                logger.exception("[WebUI] WebUI 更新失败")
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
        from pallas.console.webui.update_apply_progress import (
            create_update_apply_job,
            has_active_update_apply_job,
            run_update_apply_job,
        )
        from pallas.core.shared.utils.format_exception import format_exception_for_log

        from .webui_auto_update import auto_update_status_payload, run_auto_update_tick

        if has_active_update_apply_job():
            raise HTTPException(status_code=409, detail="update_busy")

        job = await create_update_apply_job("auto")
        logger.info("[WebUI] Immediate automatic update job [{}] queued", job.job_id)

        async def _runner(j: Any) -> None:
            def on_progress(pct: int, message: str) -> None:
                j.push("running", message, progress_percent=pct)

            try:
                tick = await run_auto_update_tick(
                    config=plugin_config,
                    force=True,
                    progress_job_id=j.job_id,
                    on_progress=on_progress,
                )
                status = auto_update_status_payload(plugin_config)
                status["tick"] = tick
                j.result = status
                overall = str((tick or {}).get("result") or "")
                if overall == "applied":
                    j.message = "已自动更新"
                elif overall == "up_to_date":
                    j.message = "各项均已是最新或无可应用更新"
                elif overall == "skipped":
                    j.message = "本轮已跳过（未开启或不可用）"
                elif overall == "failed":
                    j.message = str((tick or {}).get("error") or status.get("last_error") or "自动更新失败")
                    j.push("failed", error=j.message, progress_percent=j.progress_percent)
                else:
                    j.message = "本轮自动更新结束"
            except Exception as e:  # noqa: BLE001
                logger.exception("[WebUI] 自动更新立即执行失败")
                j.push("failed", error=format_exception_for_log(e), progress_percent=j.progress_percent)

        asyncio.create_task(run_update_apply_job(job, _runner))
        return JSONResponse({"ok": True, "data": {"job_id": job.job_id, "kind": "auto"}})

    @router.get(f"{x}/update/jobs/active", include_in_schema=True)
    async def _update_apply_job_active() -> JSONResponse:
        from pallas.console.webui.update_apply_progress import get_active_update_apply_job

        job = get_active_update_apply_job()
        return JSONResponse({"ok": True, "data": job.as_dict() if job else None})

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

        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        webui_key = _webui_update_cache_key(plugin_config)
        bot_key = f"update_check_bot:{bool(github_token)}"

        async def warm(
            key: str,
            loader,
            ttl: float,
            stale: float,
            *,
            swr: bool = False,
            persist_snapshot: bool = False,
        ) -> None:
            try:
                await cached_read(
                    key=key,
                    loader=loader,
                    ttl_sec=ttl,
                    stale_sec=stale,
                    swr=swr,
                    persist_snapshot=persist_snapshot,
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("[WebUI] Cache warm-up read failed for key [{}]: [{}]", key, e)

        async def load_webui() -> dict[str, Any]:
            return await _load_webui_update_check_payload(plugin_config)

        async def load_bot() -> dict[str, Any]:
            return await _load_bot_update_check_payload(plugin_config)

        async def load_community() -> dict[str, Any]:
            return await fetch_community_public_stats()

        from packages.pb_webui import extended_api as ext

        async def load_instances() -> dict[str, Any]:
            return await ext._instances_payload()

        async def load_plugins() -> list[dict[str, Any]]:
            return await asyncio.to_thread(ext._list_plugins_dict)

        async def load_bots() -> list[dict[str, Any]]:
            return await asyncio.to_thread(ext._list_bots_dict)

        async def load_system() -> dict[str, Any]:
            return await asyncio.to_thread(ext._system_dict)

        async def load_message_stats() -> dict[str, Any]:
            return await ext._message_stats_overview(self_id=None, include_history=False)

        async def load_plugin_run_stats() -> dict[str, Any]:
            return await asyncio.to_thread(
                ext._plugin_run_stats_overview,
                self_id=None,
                log_source="all",
                tb_limit=0,
                include_log_errors=False,
                include_history=False,
            )

        # 局部 warm 调用按键映射；本地批走 to_thread/内存，外部批经共享信号量。
        local_loader_spec: dict[str, tuple] = {
            "instances": (load_instances, 5.0, 30.0, {"swr": True, "persist_snapshot": True}),
            "plugins": (load_plugins, 1.6, 25.0, {}),
            "message-stats:all": (load_message_stats, 2.0, 10.0, {}),
            "plugin-run-stats:all:logsrc:all:tbl:0:view:full": (load_plugin_run_stats, 2.0, 10.0, {}),
            "bots": (load_bots, 0.9, 15.0, {}),
            "system": (load_system, 0.8, 8.0, {}),
        }
        external_loader_spec: dict[str, tuple] = {
            webui_key: (load_webui, 120.0, 900.0),
            bot_key: (load_bot, 120.0, 900.0),
            _COMMUNITY_STATS_WARM_KEY: (load_community, 30.0, 120.0),
        }

        local_keys, external_keys = _batch_warm_keys(webui_key, bot_key)

        async def warm_local(key: str) -> None:
            loader, ttl, stale, kwargs = local_loader_spec[key]
            await warm(key, loader, ttl, stale, **kwargs)

        async def warm_external(key: str) -> None:
            loader, ttl, stale = external_loader_spec[key]
            async with _EXTERNAL_SEM:
                await warm(key, loader, ttl, stale)

        # 本地批先建好首屏缓存；外部批延后并受共享信号量约束（同刻最多 2 路）。
        await asyncio.gather(*(warm_local(k) for k in local_keys))
        await asyncio.sleep(_STAGGER_EXTERNAL_WARM_SEC)
        await asyncio.gather(*(warm_external(k) for k in external_keys))

    global _warm_console_read_caches_fn
    _warm_console_read_caches_fn = _warm_console_read_caches_impl

    set_warm_console_read_caches_impl(_warm_console_read_caches_impl)
