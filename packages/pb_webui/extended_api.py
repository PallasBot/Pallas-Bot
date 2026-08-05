"""控制台扩展 JSON API 编排：按域路由模块注册与公开 re-export。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, Query
from nonebot import logger

from pallas.console.webui.console_login import register_console_session_invalidation_hook

from .console_metrics_runtime import (
    _ensure_log_sink,
    _scheduled_cleanup_matcher_error_logs,
    _scheduled_refresh_plugin_store_assets,
    _scheduled_refresh_plugin_update_snapshot,
    enforce_matcher_duration_log_limits,
    ensure_console_metrics_hooks,
    start_worker_shard_console_stats_sync,
)
from .console_read_cache import clear_extended_read_cache
from .extended_common import (
    build_console_openapi_schema,
)
from .extended_common import (
    require_pallas_token_configured as _require_pallas_token_configured_impl,
)
from .update_api import warm_console_read_caches

_check_pallas_write_token = _require_pallas_token_configured_impl
_require_pallas_token_configured = _require_pallas_token_configured_impl


if TYPE_CHECKING:
    from .config import Config

# Re-export metrics runtime symbols for tests / shard workers (stable import path).
from . import console_metrics_runtime as _metrics  # noqa: E402

_MSG_STATS = _metrics._MSG_STATS
_PLUGIN_RUN_STATS = _metrics._PLUGIN_RUN_STATS
_CONSOLE_CAL_DAY = _metrics._CONSOLE_CAL_DAY
_MATCHER_DURATION_LOG_CAP = _metrics._MATCHER_DURATION_LOG_CAP
_MATCHER_DURATION_LOG_PER_PLUGIN_CAP = _metrics._MATCHER_DURATION_LOG_PER_PLUGIN_CAP
_LOG_ERROR_JSONL_LOCK = _metrics._LOG_ERROR_JSONL_LOCK
_LOG_ERROR_BUFFER = _metrics._LOG_ERROR_BUFFER

_message_stats_mem_from_shard_blob = _metrics._message_stats_mem_from_shard_blob
_msg_stats_shard_export = _metrics._msg_stats_shard_export
_msg_stats_shard_import = _metrics._msg_stats_shard_import
_matcher_elapsed_ms = _metrics._matcher_elapsed_ms
mark_matcher_run_started = _metrics.mark_matcher_run_started
take_matcher_run_started = _metrics.take_matcher_run_started
_log_error_entry_matches_source = _metrics._log_error_entry_matches_source
_log_error_log_public = _metrics._log_error_log_public
_log_error_log_meta = _metrics._log_error_log_meta
_log_errors_payload = _metrics._log_errors_payload
_invalidate_log_error_public_cache = _metrics._invalidate_log_error_public_cache
_plugin_run_stats_overview = _metrics._plugin_run_stats_overview
_unified_console_live_stats_enabled = _metrics._unified_console_live_stats_enabled
_restore_unified_console_stats_from_live_file = _metrics._restore_unified_console_stats_from_live_file
_collect_console_daily_flush_entries = _metrics._collect_console_daily_flush_entries
_console_daily_stats_disk_enabled = _metrics._console_daily_stats_disk_enabled
_flush_today_console_daily_stats_disk = _metrics._flush_today_console_daily_stats_disk
flush_repeater_metrics_history_sync = _metrics.flush_repeater_metrics_history_sync
flush_ingress_metrics_history_sync = _metrics.flush_ingress_metrics_history_sync
flush_worker_shard_console_stats_sync = _metrics.flush_worker_shard_console_stats_sync
flush_worker_shard_console_stats_async = _metrics.flush_worker_shard_console_stats_async
flush_today_console_daily_stats_disk_async = _metrics.flush_today_console_daily_stats_disk_async

_message_stats_overview = _metrics._message_stats_overview

import time as time  # noqa: E402 — tests monkeypatch ext.time


def register_extended_api(
    app,
    *,
    api_base: str,
    plugin_config: Config,
    enable_runtime_hooks: bool = True,
) -> None:
    if enable_runtime_hooks:
        ensure_console_metrics_hooks()
    x = (api_base or "/pallas/api").strip()
    if not x.startswith("/"):
        x = "/" + x
    x = x.rstrip("/")

    async def _pallas_token_dep(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> None:
        _require_pallas_token_configured(
            plugin_config,
            x_pallas_token=x_pallas_token,
            token=token,
        )

    router_pub = APIRouter(tags=["Pallas-Bot 控制台"])
    router = APIRouter(tags=["Pallas-Bot 控制台"], dependencies=[Depends(_pallas_token_dep)])

    from .acl_api import register_acl_router
    from .agent_platform_api import register_agent_platform_router
    from .ai_extension_api import register_ai_extension_router
    from .auth_security_api import register_auth_security_router
    from .common_config_api import register_common_config_router
    from .db_api import register_db_router
    from .extended_common import check_pallas_write_token
    from .instances_configs_api import register_instances_configs_router
    from .llm_ops_api import register_llm_ops_router
    from .llm_product_api import register_llm_product_router
    from .logs_api import register_logs_router
    from .memory_graph_api import register_memory_graph_router
    from .plugins_console_api import register_plugins_console_router
    from .social_api import register_social_router
    from .stats_dashboard_api import register_stats_dashboard_router
    from .system_home_api import register_system_home_router
    from .update_api import register_update_router

    register_auth_security_router(
        router,
        router_pub,
        x=x,
        plugin_config=plugin_config,
        app=app,
    )
    register_acl_router(router, x=x)
    register_llm_ops_router(
        router,
        x=x,
        plugin_config=plugin_config,
        check_write_token=check_pallas_write_token,
    )
    register_memory_graph_router(
        router,
        x=x,
        plugin_config=plugin_config,
        check_write_token=check_pallas_write_token,
    )
    register_agent_platform_router(
        router,
        x=x,
        plugin_config=plugin_config,
        check_write_token=check_pallas_write_token,
    )
    register_system_home_router(router, x=x, plugin_config=plugin_config)
    register_stats_dashboard_router(router, x=x, plugin_config=plugin_config)
    register_plugins_console_router(router, x=x, plugin_config=plugin_config)
    register_common_config_router(router, x=x, plugin_config=plugin_config)
    register_llm_product_router(router, x=x, plugin_config=plugin_config)
    register_logs_router(router, x=x, plugin_config=plugin_config)
    register_db_router(router, x=x, plugin_config=plugin_config)
    register_instances_configs_router(router, x=x, plugin_config=plugin_config)
    register_ai_extension_router(router, x=x, plugin_config=plugin_config)
    register_social_router(router, x=x, plugin_config=plugin_config)
    register_update_router(router, x=x, plugin_config=plugin_config)

    if not getattr(app.state, "_pallas_ext_read_cache_inv_hook", False):
        register_console_session_invalidation_hook(clear_extended_read_cache)
        app.state._pallas_ext_read_cache_inv_hook = True

    from packages.help.console_routes import register_help_preview_routes

    register_help_preview_routes(router, api_base=x)

    app.include_router(router_pub)
    app.include_router(router)

    from packages.pb_webui.console_api_errors import register_console_api_exception_handlers

    register_console_api_exception_handlers(app, api_prefix=x)

    try:
        from nonebot_plugin_apscheduler import scheduler
    except ImportError:
        logger.warning("Pallas-Bot 控制台: 未安装 nonebot_plugin_apscheduler，跳过控制台异常记录定时清理")
    else:
        _matcher_cleanup_job_id = "pallas_webui_matcher_error_log_cleanup"
        if scheduler.get_job(_matcher_cleanup_job_id):
            scheduler.remove_job(_matcher_cleanup_job_id)
        scheduler.add_job(
            _scheduled_cleanup_matcher_error_logs,
            trigger="cron",
            hour=4,
            minute=0,
            id=_matcher_cleanup_job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        _daily_flush_id = "pallas_webui_console_daily_stats_flush"
        if scheduler.get_job(_daily_flush_id):
            scheduler.remove_job(_daily_flush_id)
        scheduler.add_job(
            _metrics._flush_today_console_daily_stats_disk,
            trigger="interval",
            minutes=2,
            id=_daily_flush_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        _plugin_update_snapshot_id = "pallas_webui_plugin_update_snapshot"
        if scheduler.get_job(_plugin_update_snapshot_id):
            scheduler.remove_job(_plugin_update_snapshot_id)
        scheduler.add_job(
            _scheduled_refresh_plugin_update_snapshot,
            trigger="cron",
            hour=4,
            minute=0,
            id=_plugin_update_snapshot_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        _plugin_store_assets_id = "pallas_webui_plugin_store_assets"
        if scheduler.get_job(_plugin_store_assets_id):
            scheduler.remove_job(_plugin_store_assets_id)
        scheduler.add_job(
            _scheduled_refresh_plugin_store_assets,
            trigger="cron",
            hour="*/6",
            minute=15,
            id=_plugin_store_assets_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        try:
            from .webui_auto_update import reschedule_webui_auto_update_job

            reschedule_webui_auto_update_job(plugin_config)
        except Exception:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 注册 WebUI 自动更新调度失败")


# Re-export domain helpers / patch targets for tests and lazy imports in domain modules.
# ruff: noqa: E402
from nonebot import get_bots  # noqa: F401

from pallas.console.webui.console_login import console_setup_status  # noqa: F401
from pallas.product.llm.behavior_store import (  # noqa: F401
    delete_behavior_pattern,
    list_behavior_runs,
    upsert_behavior_pattern,
)
from pallas.product.llm.kernel.observability import build_conversation_kernel_status  # noqa: F401
from pallas.product.llm.memory.store import list_memory_entries  # noqa: F401
from pallas.product.llm.repeater_feedback import (  # noqa: F401
    find_feedback_entry,
    set_feedback_entry_correction,
    set_feedback_entry_eligibility,
)
from pallas.product.persona.expression_bank import list_group_expressions  # noqa: F401
from pallas.product.persona.expression_promote import resolve_expression  # noqa: F401

from .ai_extension_api import _load_ai_extension_config, ai_extension_http_json  # noqa: F401
from .console_read_cache import drop_read_cache  # noqa: F401
from .extended_common import shard_hub_console as _shard_hub_console  # noqa: F401
from .extended_common import shard_worker_console as _shard_worker_console  # noqa: F401
from .instances_configs_api import _instances_payload  # noqa: F401
from .plugins_console_api import _list_plugins_dict, _resolve_community_plugin_target  # noqa: F401
from .repeater_metrics_history import repeater_metrics_history_path  # noqa: F401
from .social_api import (  # noqa: F401
    _console_bot_connection_meta,
    _console_bot_online_in_cluster,
    _doubt_friends_for_self_id_safe,
    _enrich_friend_request_rows_nicknames_for_self_id,
    _fetch_group_list_for_self_id,
    _friend_requests_overview,
    _parse_friend_list_raw,
    _read_pending_friend_requests_disk,
)
from .system_home_api import _home_overview_payload, _list_bots_dict, _system_dict  # noqa: F401
from .update_api import _bot_restart_available  # noqa: F401

__all__ = [
    "build_console_openapi_schema",
    "ensure_console_metrics_hooks",
    "enforce_matcher_duration_log_limits",
    "register_extended_api",
    "start_worker_shard_console_stats_sync",
    "warm_console_read_caches",
    "_ensure_log_sink",
]
