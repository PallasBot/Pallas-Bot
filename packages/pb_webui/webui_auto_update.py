"""控制台自动更新：WebUI dist.zip / Bot release_tag / 插件。"""

from __future__ import annotations

import json
import time
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
    from .manager import inspect_bot_deployment

    deploy = inspect_bot_deployment()
    mode = str(deploy.get("deployment_mode") or "").strip()
    web = state["targets"]["webui"]
    bot = state["targets"]["bot"]
    plugins = state["targets"]["plugins"]
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
        "webui": {
            "enabled": bool(getattr(cfg, "pallas_webui_auto_update_enabled", False)),
            **web,
        },
        "bot": {
            "enabled": bool(getattr(cfg, "pallas_bot_auto_update_enabled", False)),
            "deployment_mode": mode,
            "auto_apply_eligible": mode == "release_tag",
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

    if has_active_update_apply_job():
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

    if has_active_update_apply_job():
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

    from .manager import BotGitUpdateError, inspect_bot_deployment

    cfg = config if config is not None else get_pallas_webui_config()
    enabled = bool(getattr(cfg, "pallas_bot_auto_update_enabled", False))
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
    if mode != "release_tag":
        out = {"result": "skipped", "reason": f"deploy:{mode or 'unknown'}"}
        _patch_target(
            "bot",
            {
                "last_check_at": now,
                "last_check_result": "skipped",
                "last_error": None,
                "skip_reason": mode or "unknown",
            },
        )
        return out

    if has_active_update_apply_job():
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

    if check.get("error"):
        err = str(check.get("error") or "").strip() or "check_failed"
        _patch_target("bot", {"last_check_at": now, "last_check_result": "failed", "last_error": err})
        return {"result": "failed", "error": err}

    current_tag = str(check.get("current_tag") or "").strip()
    latest_tag = str(check.get("latest_tag") or "").strip()
    has_update = bool(check.get("has_update"))
    if not has_update or not latest_tag:
        _patch_target(
            "bot",
            {"last_check_at": now, "last_check_result": "up_to_date", "last_error": None, "skip_reason": None},
        )
        return {"result": "up_to_date", "current_tag": current_tag, "latest_tag": latest_tag}

    if has_active_update_apply_job():
        out = {"result": "skipped", "reason": "busy"}
        _patch_target(
            "bot",
            {"last_check_at": now, "last_check_result": "skipped", "last_error": None, "skip_reason": "busy"},
        )
        return out

    logger.info(
        "Pallas-Bot 控制台: Bot 自动更新开始 current={} target={}",
        current_tag or "(unknown)",
        latest_tag,
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

    updated: list[str] = []
    failed: list[dict[str, str]] = []
    for pkg in official_todo:
        try:
            await update_official_extension_with_options(pkg, restart=False)
            updated.append(pkg)
        except ExtensionInstallError as e:
            failed.append({"id": pkg, "error": e.detail})
        except Exception as e:  # noqa: BLE001
            failed.append({"id": pkg, "error": format_exception_for_log(e)})

    for pid in community_todo:
        try:
            await update_community_plugin(pid)
            updated.append(pid)
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
        _append_pending_item({
            "kind": "plugins",
            "tag": f"{len(updated)} 个插件",
            "updated": updated,
            "failed": failed,
            "applied_at": applied_at,
        })
        try:
            from pallas.console.cli.bot_process import bot_lifecycle_available, schedule_bot_restart

            if bot_lifecycle_available():
                schedule_bot_restart(delay_s=3.0)
        except Exception:  # noqa: BLE001
            logger.warning("Pallas-Bot 控制台: 插件自动更新后安排重启失败")
        try:
            from .console_read_cache import drop_read_cache

            drop_read_cache(("plugins-official-extensions", "plugins", "plugins-community-store"))
        except Exception:  # noqa: BLE001
            pass
        return {
            "result": result,
            "updated": updated,
            "failed": failed,
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
) -> dict[str, Any]:
    """统一调度一轮。force=True 时忽略各目标开关（立即执行）。"""
    from pallas.core.platform.bot_runtime.roles import is_sharded_worker

    cfg = config if config is not None else get_pallas_webui_config()
    now = time.time()
    if is_sharded_worker():
        save_auto_update_state({"last_run_at": now})
        return {"result": "skipped", "reason": "worker", "targets": {}}

    wanted: list[TargetKind]
    if targets:
        wanted = targets
    elif force:
        wanted = ["webui", "bot", "plugins"]
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
        return {"result": "skipped", "reason": "disabled", "targets": {}}

    results: dict[str, Any] = {}
    # WebUI → 插件 → Bot（Bot 可能重启）
    order: list[TargetKind] = [t for t in ("webui", "plugins", "bot") if t in wanted]
    for kind in order:
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
    return {"result": overall, "targets": results}


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
