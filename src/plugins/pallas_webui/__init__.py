# ruff: noqa: E501
import asyncio

from nonebot import get_app, get_driver, logger
from nonebot.plugin import PluginMetadata

from src.console.web import public_base_url
from src.console.webui.console_login import (
    install_pallas_http_request_context_middleware,
    prime_shared_console_login,
)
from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import join_usage, usage_line
from src.platform.bot_runtime.roles import is_sharded_worker
from src.shared.utils.format_exception import format_exception_for_log

from .api import register_api
from .config import Config, plugin_config
from .extended_api import register_extended_api, set_console_meta, warm_console_read_caches
from .manager import (
    bot_has_release_update,
    bot_is_development_build,
    check_webui_exists,
    download_and_extract_dist_zip,
    fetch_latest_bot_release,
    fetch_latest_webui_release,
    get_bot_current_version,
    get_installed_webui_version,
    get_webui_dist_version,
    github_release_asset_url,
    resolve_github_release_asset_urls,
    save_installed_webui_version,
    webui_public_path,
)
from .public import register_routes

__plugin_meta__ = PluginMetadata(
    name="Web 控制台",
    description="浏览器运维控制台与扩展 API。",
    usage=join_usage(
        usage_line("/pallas/", "控制台页面"),
        usage_line("/pallas/api/*", "实例、日志、数据库与插件统计等接口"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "menu_data": [
            {
                "func": "控制台页面",
                "trigger_method": "http",
                "help_audience": "maintainer",
                "trigger_condition": "/pallas/",
                "brief_des": "提供控制台界面",
                "detail_des": "展示实例状态、日志、数据库与插件信息。",
            },
            {
                "func": "扩展状态接口",
                "trigger_method": "http",
                "help_audience": "maintainer",
                "trigger_condition": "/pallas/api/*",
                "brief_des": "提供控制台数据接口",
                "detail_des": "提供 health、system、instances、logs、message-stats 等接口。",
            },
        ],
    },
)

app = get_app()
driver = get_driver()

if not is_sharded_worker():
    install_pallas_http_request_context_middleware(app)

# hub / unified：CORS；worker 指标见 worker_console_metrics
if not is_sharded_worker() and plugin_config.pallas_webui_enabled and plugin_config.pallas_webui_cors:
    _cors_origins = [str(o).strip() for o in (plugin_config.pallas_webui_allowed_origins or []) if str(o).strip()]
    if not _cors_origins:
        logger.warning(
            "控制台：CORS 已启用但 allowed_origins 为空",
        )
    else:
        from fastapi.middleware.cors import CORSMiddleware

        _has_wildcard = "*" in _cors_origins
        if _has_wildcard:
            logger.warning(
                "控制台：allowed_origins 含 '*'，已关闭 allow_credentials",
            )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_cors_origins,
            allow_credentials=not _has_wildcard,
            allow_methods=["*"],
            allow_headers=["*"],
        )


if not is_sharded_worker():

    @driver.on_startup
    async def _pallas_webui_startup() -> None:
        if not plugin_config.pallas_webui_enabled:
            return
        prime_shared_console_login()
        public = webui_public_path()
        base = (plugin_config.pallas_webui_http_base or "/pallas").strip()
        if not base.startswith("/"):
            base = "/" + base
        base = base.rstrip("/")
        api_base = f"{base}/api"
        register_api(
            app,
            api_base=api_base,
            extra_meta={"static_root": str(public), "http_base": base},
        )
        webui_version = get_webui_dist_version() or get_installed_webui_version().get("tag", "")
        if plugin_config.pallas_webui_dev_mode:
            logger.warning("控制台：开发模式，已关闭鉴权")
        set_console_meta({
            "static_root": str(public),
            "http_base": base,
            "version": webui_version,
            "pallas_webui_dev_mode": bool(plugin_config.pallas_webui_dev_mode),
        })
        register_extended_api(app, api_base=api_base, plugin_config=plugin_config)
        from .extended_api import _ensure_log_sink

        _ensure_log_sink()
        register_routes(
            app,
            public_dir=public,
            base=base,
            plugin_config=plugin_config,
        )
        dconf = get_driver().config
        open_base = public_base_url(
            host=getattr(dconf, "host", None),
            port=getattr(dconf, "port", None),
        )
        logger.info("控制台：{}{}/", open_base, base)

        async def _bootstrap_webui_dist() -> None:
            if check_webui_exists(public):
                return
            logger.info("控制台：首次部署，后台拉取静态资源")
            tok = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
            url = (plugin_config.pallas_webui_dist_zip_url or "").strip()
            url_candidates: list[str] = []
            resolve_err = ""
            if not url:
                try:
                    repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "")
                    asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "")
                    tag = str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or "")
                    url_candidates = await resolve_github_release_asset_urls(repo, asset, tag, token=tok)
                    url = github_release_asset_url(
                        str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or ""),
                        str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or ""),
                        str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or ""),
                    )
                except Exception as e:
                    resolve_err = format_exception_for_log(e)
                    url = ""
                    url_candidates = []
            else:
                url_candidates = [url]
            if not url:
                if resolve_err:
                    logger.error("控制台：无法解析 WebUI 下载地址 ({})", resolve_err)
                else:
                    logger.error("控制台：无法解析 WebUI 下载地址")
                return
            errors: list[str] = []
            succeeded_url = ""
            for candidate in url_candidates or [url]:
                try:
                    await download_and_extract_dist_zip(public, candidate)
                    succeeded_url = candidate
                    errors.clear()
                    break
                except Exception as e:
                    err_msg = format_exception_for_log(e)
                    errors.append(f"{candidate} -> {err_msg}")
            if errors:
                logger.error("控制台：dist 下载/解压失败: {}", " | ".join(errors))
            elif succeeded_url:
                try:
                    tag = str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or "").strip()
                    if not tag:
                        try:
                            repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "")
                            asset_fb = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "dist.zip")
                            info = await fetch_latest_webui_release(repo, token=tok, asset_name=asset_fb)
                            tag = info.get("tag", "")
                        except Exception:
                            tag = ""
                    save_installed_webui_version(tag, succeeded_url)
                except Exception:
                    pass
                logger.info("控制台：静态资源就绪，请刷新页面")
            webui_ver = get_webui_dist_version() or get_installed_webui_version().get("tag", "")
            set_console_meta({"static_root": str(public), "http_base": base, "version": webui_ver})

        async def _background_release_checks() -> None:
            tok = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
            try:
                repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "PallasBot/Pallas-Bot-WebUI")
                asset_chk = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "dist.zip")
                installed = get_installed_webui_version()
                current_tag = str(installed.get("tag", "") or "").strip()
                latest_info = await fetch_latest_webui_release(repo, token=tok, asset_name=asset_chk)
                latest_tag = str(latest_info.get("tag", "") or "").strip()
                if latest_tag and current_tag != latest_tag:
                    release_url = str(latest_info.get("html_url", "") or "").strip()
                    logger.info(
                        "console: webui update available {} (current {}){}",
                        latest_tag,
                        current_tag or "-",
                        f" → {release_url}" if release_url else "",
                    )
                else:
                    logger.debug("console: webui up to date tag={}", current_tag or "-")
            except Exception as e:
                logger.debug("console: webui update check failed: {}", format_exception_for_log(e))
            try:
                bot_current = get_bot_current_version()
                bot_current_tag = bot_current.get("tag", "")
                bot_current_commit = bot_current.get("commit", "")
                bot_latest_info = await fetch_latest_bot_release("PallasBot/Pallas-Bot", token=tok)
                bot_latest_tag = str(bot_latest_info.get("tag", "") or "").strip()
                if bot_has_release_update(
                    latest_tag=bot_latest_tag,
                    current_tag=str(bot_current_tag or ""),
                    current_commit=str(bot_current_commit or ""),
                ):
                    bot_release_url = str(bot_latest_info.get("html_url", "") or "").strip()
                    logger.info(
                        "console: bot update available {} (current {}){}",
                        bot_latest_tag,
                        bot_current_tag or bot_current_commit or "-",
                        f" → {bot_release_url}" if bot_release_url else "",
                    )
                elif bot_is_development_build(
                    latest_tag=bot_latest_tag,
                    current_tag=str(bot_current_tag or ""),
                    current_commit=str(bot_current_commit or ""),
                ):
                    logger.debug(
                        "console: bot dev build ahead of release {} commit={}",
                        bot_latest_tag,
                        bot_current_commit or "-",
                    )
                elif bot_current_tag:
                    logger.debug("console: bot up to date tag={}", bot_current_tag)
                else:
                    logger.debug("console: bot commit={}", bot_current_commit or "-")
            except Exception as e:
                logger.debug("console: bot update check failed: {}", format_exception_for_log(e))

        async def _guarded(name: str, fn):
            try:
                await fn()
            except Exception as e:
                logger.error("控制台：后台任务 {} 异常: {}", name, format_exception_for_log(e))

        if not check_webui_exists(public):
            asyncio.create_task(_guarded("webui-dist-bootstrap", _bootstrap_webui_dist))
        asyncio.create_task(_guarded("release-version-check", _background_release_checks))
        asyncio.create_task(_guarded("console-read-cache-warm", warm_console_read_caches))
