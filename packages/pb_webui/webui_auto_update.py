"""控制台自动更新：WebUI dist.zip / Bot release_tag / 插件。"""

from __future__ import annotations

import json
import time
import tomllib
from typing import TYPE_CHECKING, Any, Literal

from nonebot import logger

from pallas.console.cli.update_ops import WebuiUpdateError, apply_bot_update, apply_webui_dist_update
from pallas.console.webui.update_apply_progress import has_active_update_apply_job

if TYPE_CHECKING:
    from pathlib import Path

AUTO_UPDATE_JOB_ID = "pallas_webui_auto_update"
TargetKind = Literal["webui", "bot", "plugins"]


def auto_update_state_path() -> Path:
    from .data_dir import pb_webui_data_dir

    return pb_webui_data_dir() / "auto_update_state.json"


def _empty_target_state() -> dict[str, Any]:
    return {
        "last_check_at": None,
        "last_check_result": None,
        "last_applied_tag": None,
        "last_applied_at": None,
        "last_error": None,
        "updated": None,
        "failed": None,
        "skip_reason": None,
    }


def _empty_state() -> dict[str, Any]:
    return {
        "last_run_at": None,
        "pending_notice": None,
        "targets": {
            "webui": _empty_target_state(),
            "bot": _empty_target_state(),
            "plugins": _empty_target_state(),
        },
        # 兼容旧扁平字段（仅 webui）
        "last_check_at": None,
        "last_check_result": None,
        "last_applied_tag": None,
        "last_applied_at": None,
        "last_error": None,
    }


def _migrate_state(raw: dict[str, Any]) -> dict[str, Any]:
    state = _empty_state()
    targets = raw.get("targets")
    if isinstance(targets, dict):
        for kind in ("webui", "bot", "plugins"):
            entry = targets.get(kind)
            if isinstance(entry, dict):
                merged = _empty_target_state()
                merged.update({k: entry.get(k) for k in merged})
                state["targets"][kind] = merged
    else:
        # 旧版仅 webui 扁平字段
        web = _empty_target_state()
        for key in web:
            if key in raw:
                web[key] = raw[key]
        state["targets"]["webui"] = web
    if "pending_notice" in raw:
        state["pending_notice"] = raw.get("pending_notice")
    if "last_run_at" in raw:
        state["last_run_at"] = raw.get("last_run_at")
    # 同步扁平兼容字段
    web = state["targets"]["webui"]
    state["last_check_at"] = web.get("last_check_at")
    state["last_check_result"] = web.get("last_check_result")
    state["last_applied_tag"] = web.get("last_applied_tag")
    state["last_applied_at"] = web.get("last_applied_at")
    state["last_error"] = web.get("last_error")
    return state


def load_auto_update_state() -> dict[str, Any]:
    path = auto_update_state_path()
    if not path.exists():
        return _empty_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return _empty_state()
    if not isinstance(raw, dict):
        return _empty_state()
    return _migrate_state(raw)


def save_auto_update_state(patch: dict[str, Any]) -> dict[str, Any]:
    state = load_auto_update_state()
    if "targets" in patch and isinstance(patch["targets"], dict):
        for kind, entry in patch["targets"].items():
            if kind not in state["targets"] or not isinstance(entry, dict):
                continue
            state["targets"][kind].update(entry)
        patch = {k: v for k, v in patch.items() if k != "targets"}
    state.update(patch)
    web = state["targets"]["webui"]
    state["last_check_at"] = web.get("last_check_at")
    state["last_check_result"] = web.get("last_check_result")
    state["last_applied_tag"] = web.get("last_applied_tag")
    state["last_applied_at"] = web.get("last_applied_at")
    state["last_error"] = web.get("last_error")
    path = auto_update_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def _patch_target(kind: TargetKind, patch: dict[str, Any]) -> dict[str, Any]:
    return save_auto_update_state({"targets": {kind: patch}})


def _append_pending_item(item: dict[str, Any]) -> dict[str, Any]:
    state = load_auto_update_state()
    notice = state.get("pending_notice")
    items: list[dict[str, Any]] = []
    if isinstance(notice, dict):
        raw_items = notice.get("items")
        if isinstance(raw_items, list):
            items = [x for x in raw_items if isinstance(x, dict)]
        elif notice.get("tag") or notice.get("kind"):
            # 旧单条 notice
            items = [dict(notice)]
    items.append(item)
    return save_auto_update_state({"pending_notice": {"items": items}})


def ack_pending_notice() -> dict[str, Any]:
    return save_auto_update_state({"pending_notice": None})


def get_pallas_webui_config():
    from .config import get_pallas_webui_config as _get

    return _get()


async def _load_webui_check(config: Any) -> dict[str, Any]:
    from .update_api import _load_webui_update_check_payload

    return await _load_webui_update_check_payload(config)


async def _load_bot_check(config: Any) -> dict[str, Any]:
    from .update_api import _load_bot_update_check_payload

    return await _load_bot_update_check_payload(config)


def _schedule_fields(cfg: Any) -> dict[str, Any]:
    mode = str(getattr(cfg, "pallas_webui_auto_update_schedule_mode", "interval") or "interval").strip().lower()
    if mode not in ("interval", "cron"):
        mode = "interval"
    return {
        "schedule_mode": mode,
        "interval_hours": int(getattr(cfg, "pallas_webui_auto_update_interval_hours", 6) or 6),
        "cron_hour": int(getattr(cfg, "pallas_webui_auto_update_cron_hour", 4) or 0),
        "cron_minute": int(getattr(cfg, "pallas_webui_auto_update_cron_minute", 0) or 0),
    }


def _any_auto_enabled(cfg: Any) -> bool:
    return bool(
        getattr(cfg, "pallas_webui_auto_update_enabled", False)
        or getattr(cfg, "pallas_bot_auto_update_enabled", False)
        or getattr(cfg, "pallas_plugins_auto_update_enabled", False)
    )


def auto_update_status_payload(config: Any | None = None) -> dict[str, Any]:
    cfg = config if config is not None else get_pallas_webui_config()
    state = load_auto_update_state()
    sched = _schedule_fields(cfg)
    from .manager import inspect_bot_deployment, normalize_bot_update_track

    deploy = inspect_bot_deployment()
    mode = str(deploy.get("deployment_mode") or "").strip()
    from .bot_git_manage import normalize_bot_git_track_branch

    update_track = normalize_bot_update_track(getattr(cfg, "pallas_bot_update_track", "release"))
    update_branch = normalize_bot_git_track_branch(getattr(cfg, "pallas_bot_update_branch", "") or "")
    if update_track == "branch":
        auto_apply_eligible = bool(deploy.get("git_available")) and mode != "docker"
    else:
        auto_apply_eligible = mode in {"release_tag", "docker"}
    web = state["targets"]["webui"]
    bot = state["targets"]["bot"]
    plugins = state["targets"]["plugins"]
    notify_bot_id = int(getattr(cfg, "pallas_auto_update_notify_bot_id", 0) or 0)
    return {
        **sched,
        # 兼容旧前端字段（等同 webui）
        "enabled": bool(getattr(cfg, "pallas_webui_auto_update_enabled", False)),
        "last_check_at": web.get("last_check_at"),
        "last_check_result": web.get("last_check_result"),
        "last_applied_tag": web.get("last_applied_tag"),
        "last_applied_at": web.get("last_applied_at"),
        "last_error": web.get("last_error"),
        "pending_notice": state.get("pending_notice"),
        "notify_superusers": bool(getattr(cfg, "pallas_auto_update_notify_superusers", False)),
        "notify_bot_id": notify_bot_id,
        "webui": {
            "enabled": bool(getattr(cfg, "pallas_webui_auto_update_enabled", False)),
            **web,
        },
        "bot": {
            "enabled": bool(getattr(cfg, "pallas_bot_auto_update_enabled", False)),
            "deployment_mode": mode,
            "update_track": update_track,
            "update_branch": update_branch,
            "auto_apply_eligible": auto_apply_eligible,
            **bot,
        },
        "plugins": {
            "enabled": bool(getattr(cfg, "pallas_plugins_auto_update_enabled", False)),
            **plugins,
        },
        "last_run_at": state.get("last_run_at"),
    }


async def run_webui_auto_update_tick(
    *,
    config: Any | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """仅 WebUI 一轮（供单测与兼容）。"""
    return await _run_webui_target(config=config, force=force)


async def _run_webui_target(*, config: Any | None = None, force: bool = False) -> dict[str, Any]:
    from pallas.core.shared.utils.format_exception import format_exception_for_log

    cfg = config if config is not None else get_pallas_webui_config()
    enabled = bool(getattr(cfg, "pallas_webui_auto_update_enabled", False))
    now = time.time()

    if not enabled and not force:
        out = {"result": "skipped", "reason": "disabled"}
        _patch_target(
            "webui",
            {"last_check_at": now, "last_check_result": "skipped", "last_error": None, "skip_reason": "disabled"},
        )
        return out

    if has_active_update_apply_job(kinds=("webui", "bot")):
        out = {"result": "skipped", "reason": "busy"}
        _patch_target(
            "webui",
            {"last_check_at": now, "last_check_result": "skipped", "last_error": None, "skip_reason": "busy"},
        )
        return out

    try:
        check = await _load_webui_check(cfg)
    except Exception as e:  # noqa: BLE001
        err = format_exception_for_log(e)
        logger.warning("Pallas-Bot 控制台: WebUI 自动更新检查失败 err={}", err)
        _patch_target("webui", {"last_check_at": now, "last_check_result": "failed", "last_error": err})
        return {"result": "failed", "error": err}

    if check.get("error"):
        err = str(check.get("error") or "").strip() or "check_failed"
        _patch_target("webui", {"last_check_at": now, "last_check_result": "failed", "last_error": err})
        return {"result": "failed", "error": err}

    current_tag = str(check.get("current_tag") or "").strip()
    latest_tag = str(check.get("latest_tag") or "").strip()
    has_update = bool(check.get("has_update"))
    if not has_update or not latest_tag:
        _patch_target(
            "webui",
            {"last_check_at": now, "last_check_result": "up_to_date", "last_error": None, "skip_reason": None},
        )
        return {"result": "up_to_date", "current_tag": current_tag, "latest_tag": latest_tag}

    if has_active_update_apply_job(kinds=("webui", "bot")):
        out = {"result": "skipped", "reason": "busy"}
        _patch_target(
            "webui",
            {"last_check_at": now, "last_check_result": "skipped", "last_error": None, "skip_reason": "busy"},
        )
        return out

    repo = str(getattr(cfg, "pallas_webui_dist_zip_repo", "") or "PallasBot/Pallas-Bot")
    asset = str(getattr(cfg, "pallas_webui_dist_zip_asset", "") or "dist.zip")
    tag = str(getattr(cfg, "pallas_webui_dist_zip_tag", "") or "").strip() or latest_tag
    logger.info(
        "Pallas-Bot 控制台: WebUI 自动更新开始 current={} target={}",
        current_tag or "(unknown)",
        tag,
    )
    try:
        data = await apply_webui_dist_update(
            repo=repo,
            asset=asset,
            tag=tag,
            refresh_runtime_meta=True,
        )
    except WebuiUpdateError as e:
        err = e.detail
        logger.warning("Pallas-Bot 控制台: WebUI 自动更新失败 err={}", err)
        _patch_target("webui", {"last_check_at": now, "last_check_result": "failed", "last_error": err})
        return {"result": "failed", "error": err}
    except Exception as e:  # noqa: BLE001
        err = format_exception_for_log(e)
        logger.exception("Pallas-Bot 控制台: WebUI 自动更新异常")
        _patch_target("webui", {"last_check_at": now, "last_check_result": "failed", "last_error": err})
        return {"result": "failed", "error": err}

    applied_tag = str(data.get("tag") or tag or latest_tag).strip()
    applied_at = time.time()
    notice_item = {
        "kind": "webui",
        "tag": applied_tag,
        "from_tag": current_tag,
        "applied_at": applied_at,
    }
    _patch_target(
        "webui",
        {
            "last_check_at": applied_at,
            "last_check_result": "applied",
            "last_applied_tag": applied_tag,
            "last_applied_at": applied_at,
            "last_error": None,
            "skip_reason": None,
        },
    )
    _append_pending_item(notice_item)
    try:
        from .console_read_cache import drop_read_cache

        drop_read_cache(("update_check_webui:",))
    except Exception:  # noqa: BLE001
        pass
    logger.info("Pallas-Bot 控制台: WebUI 自动更新完成 tag={}", applied_tag)
    return {
        "result": "applied",
        "tag": applied_tag,
        "from_tag": current_tag,
        "message": str(data.get("message") or "更新成功"),
        "pending_notice": notice_item,
    }


async def _run_bot_target(*, config: Any | None = None, force: bool = False) -> dict[str, Any]:
    from pallas.core.shared.utils.format_exception import format_exception_for_log

    from .manager import BotGitUpdateError, inspect_bot_deployment, normalize_bot_update_track

    cfg = config if config is not None else get_pallas_webui_config()
    enabled = bool(getattr(cfg, "pallas_bot_auto_update_enabled", False))
    update_track = normalize_bot_update_track(getattr(cfg, "pallas_bot_update_track", "release"))
    now = time.time()

    if not enabled and not force:
        out = {"result": "skipped", "reason": "disabled"}
        _patch_target(
            "bot",
            {"last_check_at": now, "last_check_result": "skipped", "last_error": None, "skip_reason": "disabled"},
        )
        return out

    deploy = inspect_bot_deployment()
    mode = str(deploy.get("deployment_mode") or "").strip()
    if update_track == "branch":
        eligible = bool(deploy.get("git_available")) and mode != "docker"
        skip_reason = (mode or "unknown") if not eligible else ""
    else:
        eligible = mode in {"release_tag", "docker"}
        skip_reason = (mode or "unknown") if not eligible else ""
    if not eligible:
        out = {"result": "skipped", "reason": f"deploy:{skip_reason or 'unknown'}"}
        _patch_target(
            "bot",
            {
                "last_check_at": now,
                "last_check_result": "skipped",
                "last_error": None,
                "skip_reason": skip_reason or "unknown",
            },
        )
        return out

    if has_active_update_apply_job(kinds=("webui", "bot")):
        out = {"result": "skipped", "reason": "busy"}
        _patch_target(
            "bot",
            {"last_check_at": now, "last_check_result": "skipped", "last_error": None, "skip_reason": "busy"},
        )
        return out

    try:
        check = await _load_bot_check(cfg)
    except Exception as e:  # noqa: BLE001
        err = format_exception_for_log(e)
        logger.warning("Pallas-Bot 控制台: Bot 自动更新检查失败 err={}", err)
        _patch_target("bot", {"last_check_at": now, "last_check_result": "failed", "last_error": err})
        return {"result": "failed", "error": err}

    if check.get("error") and not check.get("has_update"):
        err = str(check.get("error") or "").strip() or "check_failed"
        _patch_target("bot", {"last_check_at": now, "last_check_result": "failed", "last_error": err})
        return {"result": "failed", "error": err}

    current_tag = str(check.get("current_tag") or "").strip()
    latest_tag = str(check.get("latest_tag") or "").strip()
    latest_commit = str(check.get("latest_commit") or "").strip()
    target_label = latest_tag if update_track == "release" else (latest_commit or str(check.get("upstream_ref") or ""))
    has_update = bool(check.get("has_update"))
    if not has_update or (update_track == "release" and not latest_tag):
        _patch_target(
            "bot",
            {"last_check_at": now, "last_check_result": "up_to_date", "last_error": None, "skip_reason": None},
        )
        return {"result": "up_to_date", "current_tag": current_tag, "latest_tag": latest_tag}

    if has_active_update_apply_job(kinds=("webui", "bot")):
        out = {"result": "skipped", "reason": "busy"}
        _patch_target(
            "bot",
            {"last_check_at": now, "last_check_result": "skipped", "last_error": None, "skip_reason": "busy"},
        )
        return out

    logger.info(
        "Pallas-Bot 控制台: Bot 自动更新开始 track={} current={} target={}",
        update_track,
        current_tag or "(unknown)",
        target_label or "(unknown)",
    )
    try:
        data = await apply_bot_update(restart=True)
    except BotGitUpdateError as e:
        err = e.detail
        logger.warning("Pallas-Bot 控制台: Bot 自动更新失败 err={}", err)
        _patch_target("bot", {"last_check_at": now, "last_check_result": "failed", "last_error": err})
        return {"result": "failed", "error": err}
    except Exception as e:  # noqa: BLE001
        err = format_exception_for_log(e)
        logger.exception("Pallas-Bot 控制台: Bot 自动更新异常")
        _patch_target("bot", {"last_check_at": now, "last_check_result": "failed", "last_error": err})
        return {"result": "failed", "error": err}

    applied_tag = str(data.get("tag") or latest_tag).strip()
    applied_at = time.time()
    notice_item = {
        "kind": "bot",
        "tag": applied_tag,
        "from_tag": current_tag,
        "applied_at": applied_at,
    }
    _patch_target(
        "bot",
        {
            "last_check_at": applied_at,
            "last_check_result": "applied",
            "last_applied_tag": applied_tag,
            "last_applied_at": applied_at,
            "last_error": None,
            "skip_reason": None,
        },
    )
    _append_pending_item(notice_item)
    try:
        from .console_read_cache import drop_read_cache

        drop_read_cache(("update_check_bot:",))
    except Exception:  # noqa: BLE001
        pass
    logger.info("Pallas-Bot 控制台: Bot 自动更新完成 tag={}", applied_tag)
    return {
        "result": "applied",
        "tag": applied_tag,
        "from_tag": current_tag,
        "message": str(data.get("message") or "更新成功"),
        "restart_scheduled": bool(data.get("restart_scheduled")),
        "pending_notice": notice_item,
    }


async def _run_plugins_target(*, config: Any | None = None, force: bool = False) -> dict[str, Any]:
    from pallas.console.cli.extension_ops import ExtensionInstallError, update_official_extension_with_options
    from pallas.console.webui.community_plugin_install import (
        CommunityPluginInstallError,
        local_plugin_installed,
        update_community_plugin,
    )
    from pallas.console.webui.plugin_update_snapshot import refresh_plugin_update_snapshot
    from pallas.core.shared.utils.format_exception import format_exception_for_log

    cfg = config if config is not None else get_pallas_webui_config()
    enabled = bool(getattr(cfg, "pallas_plugins_auto_update_enabled", False))
    now = time.time()

    if not enabled and not force:
        out = {"result": "skipped", "reason": "disabled"}
        _patch_target(
            "plugins",
            {"last_check_at": now, "last_check_result": "skipped", "last_error": None, "skip_reason": "disabled"},
        )
        return out

    try:
        snap = await refresh_plugin_update_snapshot()
    except Exception as e:  # noqa: BLE001
        err = format_exception_for_log(e)
        logger.warning("Pallas-Bot 控制台: 插件自动更新快照失败 err={}", err)
        _patch_target("plugins", {"last_check_at": now, "last_check_result": "failed", "last_error": err})
        return {"result": "failed", "error": err}

    official = snap.get("official") if isinstance(snap.get("official"), dict) else {}
    community = snap.get("community") if isinstance(snap.get("community"), dict) else {}
    official_todo = [
        pkg
        for pkg, entry in official.items()
        if isinstance(entry, dict) and entry.get("has_update") is True and str(pkg).strip()
    ]
    community_todo = [
        pid
        for pid, entry in community.items()
        if isinstance(entry, dict)
        and entry.get("has_update") is True
        and str(pid).strip()
        and local_plugin_installed(str(pid).strip())
    ]

    if not official_todo and not community_todo:
        _patch_target(
            "plugins",
            {
                "last_check_at": now,
                "last_check_result": "up_to_date",
                "last_error": None,
                "updated": [],
                "failed": [],
                "skip_reason": None,
            },
        )
        return {"result": "up_to_date", "updated": [], "failed": []}

    updated: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    for pkg in official_todo:
        try:
            await update_official_extension_with_options(pkg, restart=False)
            entry = official.get(pkg) or {}
            updated.append({
                "id": pkg,
                "source": "official",
                "from_ref": str(entry.get("installed_ref") or "").strip(),
                "to_ref": str(entry.get("latest_ref") or "").strip(),
                "ref_kind": "version",
            })
        except ExtensionInstallError as e:
            failed.append({"id": pkg, "error": e.detail})
        except Exception as e:  # noqa: BLE001
            failed.append({"id": pkg, "error": format_exception_for_log(e)})

    for pid in community_todo:
        try:
            before_version = _community_plugin_version(pid)
            await update_community_plugin(pid)
            after_version = _community_plugin_version(pid)
            entry = community.get(pid) or {}
            if before_version and after_version and before_version != after_version:
                from_ref, to_ref, ref_kind = before_version, after_version, "version"
            else:
                from_ref = str(entry.get("installed_ref") or "").strip()
                to_ref = str(entry.get("latest_ref") or "").strip()
                ref_kind = "commit"
            updated.append({
                "id": pid,
                "source": "community",
                "from_ref": from_ref,
                "to_ref": to_ref,
                "ref_kind": ref_kind,
            })
        except CommunityPluginInstallError as e:
            failed.append({"id": pid, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            failed.append({"id": pid, "error": format_exception_for_log(e)})

    applied_at = time.time()
    if updated:
        result = "applied" if not failed else "partial"
        _patch_target(
            "plugins",
            {
                "last_check_at": applied_at,
                "last_check_result": result,
                "last_applied_tag": f"{len(updated)} plugins",
                "last_applied_at": applied_at,
                "last_error": None if not failed else f"{len(failed)} failed",
                "updated": updated,
                "failed": failed,
                "skip_reason": None,
            },
        )
        restart_scheduled = False
        try:
            from pallas.console.cli.bot_process import bot_lifecycle_available, schedule_bot_restart

            if bot_lifecycle_available():
                restart_scheduled = bool(schedule_bot_restart(delay_s=3.0))
        except Exception:  # noqa: BLE001
            logger.warning("Pallas-Bot 控制台: 插件自动更新后安排重启失败")
        _append_pending_item({
            "kind": "plugins",
            "tag": f"{len(updated)} 个插件",
            "updated": updated,
            "failed": failed,
            "restart_scheduled": restart_scheduled,
            "applied_at": applied_at,
        })
        try:
            from .console_read_cache import drop_read_cache

            drop_read_cache(("plugins-official-extensions", "plugins", "plugins-community-store"))
        except Exception:  # noqa: BLE001
            pass
        return {
            "result": result,
            "updated": updated,
            "failed": failed,
            "restart_scheduled": restart_scheduled,
            "message": f"已更新 {len(updated)} 个插件",
        }

    err = failed[0]["error"] if failed else "update_failed"
    _patch_target(
        "plugins",
        {
            "last_check_at": applied_at,
            "last_check_result": "failed",
            "last_error": err,
            "updated": [],
            "failed": failed,
        },
    )
    return {"result": "failed", "updated": [], "failed": failed, "error": err}


async def run_auto_update_tick(
    *,
    config: Any | None = None,
    force: bool = False,
    targets: list[TargetKind] | None = None,
    progress_job_id: str | None = None,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """统一调度一轮。force=True 时仍只跑已开启的目标（立即执行）。"""
    from pallas.core.platform.bot_runtime.roles import is_sharded_worker

    cfg = config if config is not None else get_pallas_webui_config()
    now = time.time()

    def push(pct: int, message: str) -> None:
        if callable(on_progress):
            on_progress(pct, message)

    if is_sharded_worker():
        save_auto_update_state({"last_run_at": now})
        return {"result": "skipped", "reason": "worker", "targets": {}}

    if has_active_update_apply_job(exclude_job_id=progress_job_id):
        save_auto_update_state({"last_run_at": now})
        push(100, "已有更新任务进行中，本轮跳过")
        return {"result": "skipped", "reason": "busy", "targets": {}}

    wanted: list[TargetKind]
    if targets:
        wanted = targets
    else:
        wanted = []
        if getattr(cfg, "pallas_webui_auto_update_enabled", False):
            wanted.append("webui")
        if getattr(cfg, "pallas_bot_auto_update_enabled", False):
            wanted.append("bot")
        if getattr(cfg, "pallas_plugins_auto_update_enabled", False):
            wanted.append("plugins")

    if not wanted:
        save_auto_update_state({"last_run_at": now})
        push(100, "未开启任何自动更新目标")
        return {"result": "skipped", "reason": "disabled", "targets": {}}

    results: dict[str, Any] = {}
    # WebUI → 插件 → Bot（Bot 可能重启）
    order: list[TargetKind] = [t for t in ("webui", "plugins", "bot") if t in wanted]
    labels = {"webui": "控制台 WebUI", "plugins": "插件", "bot": "Bot 本体"}
    push(2, "开始检查并应用…")
    for idx, kind in enumerate(order):
        base = int(5 + (90 * idx) / max(len(order), 1))
        push(base, f"正在处理：{labels.get(kind, kind)}")
        if kind == "webui":
            results["webui"] = await _run_webui_target(config=cfg, force=force)
        elif kind == "plugins":
            results["plugins"] = await _run_plugins_target(config=cfg, force=force)
        else:
            results["bot"] = await _run_bot_target(config=cfg, force=force)

    save_auto_update_state({"last_run_at": time.time()})
    applied = any(str((results.get(k) or {}).get("result") or "") in ("applied", "partial") for k in results)
    failed = any(str((results.get(k) or {}).get("result") or "") == "failed" for k in results)
    overall = "applied" if applied else ("failed" if failed else "up_to_date")
    if all(str((results.get(k) or {}).get("result") or "") == "skipped" for k in results):
        overall = "skipped"
    push(100, "本轮自动更新结束")
    if applied:
        notice_items = [
            {"kind": kind, **(row if isinstance(row, dict) else {})}
            for kind, row in results.items()
            if str((row or {}).get("result") or "") in ("applied", "partial")
        ]
        try:
            await notify_superusers_auto_update(notice_items, config=cfg)
        except Exception:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 自动更新私聊超管汇报失败")
    return {"result": overall, "targets": results}


def _community_plugin_version(plugin_id: str) -> str:
    from pallas.console.webui.community_plugin_install import plugin_install_path

    root = plugin_install_path(plugin_id)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = data.get("project") if isinstance(data, dict) else None
            version = project.get("version") if isinstance(project, dict) else None
            if isinstance(version, str) and version.strip():
                return version.strip()
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return ""


def format_plugin_update_item(item: Any) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return str(item)
    plugin_id = str(item.get("id") or item.get("plugin_id") or "未知插件").strip()
    from_ref = str(item.get("from_ref") or "").strip()
    to_ref = str(item.get("to_ref") or "").strip()
    ref_kind = str(item.get("ref_kind") or "").strip()
    detail = f"{from_ref} -> {to_ref}" if from_ref and to_ref else (to_ref or from_ref or "版本未知")
    suffix = "（提交）" if ref_kind == "commit" else ""
    return f"{plugin_id}：{detail}{suffix}"


def format_auto_update_notify_message(items: list[dict[str, Any]]) -> str:
    lines = ["【自动更新完成】", "本轮已应用："]
    labels = {"webui": "WebUI", "bot": "Bot", "plugins": "插件"}
    for item in items:
        kind = str(item.get("kind") or "").strip()
        label = labels.get(kind, kind or "项")
        tag = str(item.get("tag") or item.get("last_applied_tag") or item.get("message") or "").strip()
        from_tag = str(item.get("from_tag") or "").strip()
        if kind in {"webui", "bot"} and from_tag and tag:
            tag = f"{from_tag} -> {tag}"
        if kind == "plugins":
            updated = item.get("updated")
            if isinstance(updated, list) and updated:
                lines.append(f"· {label}（{len(updated)} 个）：")
                lines.extend(f"  - {format_plugin_update_item(row)}" for row in updated)
                failed = item.get("failed")
                if isinstance(failed, list) and failed:
                    lines.extend(
                        f"  - 失败：{entry.get('id')}（{entry.get('error')}）"
                        for entry in failed
                        if isinstance(entry, dict)
                    )
                if item.get("restart_scheduled"):
                    lines.append("· 已安排重启 Bot")
                continue
            elif not tag:
                tag = "已更新"
        lines.append(f"· {label}" + (f"：{tag}" if tag else ""))
    return "\n".join(lines)


async def notify_superusers_auto_update(
    items: list[dict[str, Any]],
    *,
    config: Any | None = None,
) -> dict[str, Any]:
    """有成功应用时私聊 SUPERUSERS；受配置开关与汇报 Bot 号约束。"""
    cfg = config if config is not None else get_pallas_webui_config()
    if not bool(getattr(cfg, "pallas_auto_update_notify_superusers", False)):
        return {"sent": False, "reason": "disabled"}
    clean = [item for item in items if isinstance(item, dict)]
    if not clean:
        return {"sent": False, "reason": "empty"}

    from nonebot import get_bots, get_driver

    bots = get_bots()
    if not bots:
        logger.warning("Pallas-Bot 控制台: 自动更新汇报时无在线 Bot")
        return {"sent": False, "reason": "no_bot"}

    prefer = int(getattr(cfg, "pallas_auto_update_notify_bot_id", 0) or 0)
    bot = None
    if prefer > 0:
        for candidate in bots.values():
            try:
                if int(candidate.self_id) == prefer:
                    bot = candidate
                    break
            except (TypeError, ValueError):
                continue
        if bot is None:
            logger.warning("Pallas-Bot 控制台: 汇报 Bot {} 不在线，跳过私聊", prefer)
            return {"sent": False, "reason": "bot_offline", "bot_id": prefer}
    else:
        bot = next(iter(bots.values()))

    superusers: list[int] = []
    for raw in get_driver().config.superusers:
        try:
            superusers.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not superusers:
        return {"sent": False, "reason": "no_superusers"}

    message = format_auto_update_notify_message(clean)
    delivered = 0
    for uid in superusers:
        try:
            await bot.send_private_msg(user_id=uid, message=message)
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Pallas-Bot 控制台: 自动更新私聊失败 bot={} user={} err={}",
                getattr(bot, "self_id", "?"),
                uid,
                exc,
            )
    return {
        "sent": delivered > 0,
        "delivered": delivered,
        "bot_id": int(getattr(bot, "self_id", 0) or 0),
    }


def reschedule_webui_auto_update_job(config: Any | None = None) -> None:
    """按配置注册/移除 apscheduler job（任一目标开启即调度）。"""
    from pallas.core.platform.bot_runtime.roles import is_sharded_worker

    if is_sharded_worker():
        return

    try:
        from nonebot_plugin_apscheduler import scheduler
    except ImportError:
        logger.warning("Pallas-Bot 控制台: 未安装 nonebot_plugin_apscheduler，跳过自动更新调度")
        return

    cfg = config if config is not None else get_pallas_webui_config()
    if scheduler.get_job(AUTO_UPDATE_JOB_ID):
        scheduler.remove_job(AUTO_UPDATE_JOB_ID)

    if not _any_auto_enabled(cfg):
        logger.info("Pallas-Bot 控制台: 自动更新已全部关闭（未注册调度）")
        return

    mode = str(getattr(cfg, "pallas_webui_auto_update_schedule_mode", "interval") or "interval").strip().lower()
    if mode not in ("interval", "cron"):
        mode = "interval"

    async def _job() -> None:
        try:
            await run_auto_update_tick()
        except Exception:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 自动更新调度执行失败")

    if mode == "cron":
        hour = max(0, min(23, int(getattr(cfg, "pallas_webui_auto_update_cron_hour", 4) or 0)))
        minute = max(0, min(59, int(getattr(cfg, "pallas_webui_auto_update_cron_minute", 0) or 0)))
        scheduler.add_job(
            _job,
            trigger="cron",
            hour=hour,
            minute=minute,
            id=AUTO_UPDATE_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        logger.info("Pallas-Bot 控制台: 自动更新已调度 cron={:02d}:{:02d}", hour, minute)
        return

    hours = int(getattr(cfg, "pallas_webui_auto_update_interval_hours", 6) or 6)
    hours = max(1, min(168, hours))
    scheduler.add_job(
        _job,
        trigger="interval",
        hours=hours,
        id=AUTO_UPDATE_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    logger.info("Pallas-Bot 控制台: 自动更新已调度 interval={}h", hours)
