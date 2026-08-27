# ruff: noqa: E501
import asyncio

from nonebot import get_app, get_driver, logger

from pallas.console.web import public_base_url
from pallas.console.webui.console_login import (
    install_pallas_http_request_context_middleware,
    prime_shared_console_login,
)
from pallas.core.foundation.startup_report import (
    register_startup_fact,
    register_startup_ready,
    register_startup_scheduled,
    register_startup_warning,
)
from pallas.core.platform.bot_runtime.roles import is_sharded_worker
from pallas.core.shared.utils.format_exception import format_exception_for_log

from .api import register_api
from .config import plugin_config
from .console_meta_store import set_console_meta
from .extended_api import register_extended_api, warm_console_read_caches
from .manager import (
    DEFAULT_WEBUI_DIST_ZIP_REPO,
    bot_has_release_update,
    bot_is_development_build,
    check_webui_exists,
    download_and_extract_dist_zip,
    extract_bundled_webui_dist,
    fetch_latest_bot_release,
    get_bot_current_version,
    get_installed_webui_version,
    get_webui_dist_version,
    normalize_webui_dist_zip_repo,
    resolve_compatible_webui_release,
    save_installed_webui_version,
    webui_frontend_stack,
    webui_has_release_update,
    webui_public_path,
)
from .public import register_routes

app = get_app()
driver = get_driver()


async def resolve_webui_release_for_runtime(
    repo: str,
    asset: str,
    tag: str = "",
    *,
    token: str = "",
) -> dict[str, object]:
    repo_name = normalize_webui_dist_zip_repo(repo or DEFAULT_WEBUI_DIST_ZIP_REPO)
    asset_name = (asset or "dist.zip").strip() or "dist.zip"
    tag_name = (tag or "").strip()
    return await resolve_compatible_webui_release(repo_name, asset_name, tag_name, token=token)


if not is_sharded_worker():
    install_pallas_http_request_context_middleware(app)

if not is_sharded_worker() and plugin_config.pallas_webui_enabled and plugin_config.pallas_webui_cors:
    _cors_origins = [str(o).strip() for o in (plugin_config.pallas_webui_allowed_origins or []) if str(o).strip()]
    if not _cors_origins:
        logger.warning(
            "[WebUI] CORS 已启用但 allowed_origins 为空",
        )
    else:
        from fastapi.middleware.cors import CORSMiddleware

        _has_wildcard = "*" in _cors_origins
        if _has_wildcard:
            logger.warning(
                "[WebUI] allowed_origins 含 '*'，已关闭 allow_credentials",
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
    async def pb_webui_startup() -> None:
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
        frontend = webui_frontend_stack()
        webui_version = get_webui_dist_version() or get_installed_webui_version().get("tag", "")
        if plugin_config.pallas_webui_dev_mode:
            logger.warning("[WebUI] 当前为开发模式，登录鉴权已关闭")
        logger.info("[WebUI] 前端栈 [{}] | 静态资源 [{}]", frontend, public)
        set_console_meta({
            "static_root": str(public),
            "http_base": base,
            "version": webui_version,
            "frontend": frontend,
            "pallas_webui_dev_mode": bool(plugin_config.pallas_webui_dev_mode),
        })
        register_extended_api(app, api_base=api_base, plugin_config=plugin_config)
        from .db_lifecycle_scheduler import install_database_lifecycle_schedule

        install_database_lifecycle_schedule()
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
        register_startup_fact("console", f"{open_base}{base}/")

        async def bootstrap_webui_dist() -> None:
            if check_webui_exists(public):
                return
            logger.info("[WebUI] 首次部署，正在初始化静态资源")
            tok = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
            if await extract_bundled_webui_dist(
                public,
                require_compatible_manifest=True,
                token=tok,
            ):
                webui_ver = get_webui_dist_version()
                set_console_meta({"static_root": str(public), "http_base": base, "version": webui_ver})
                logger.info("[WebUI] 静态资源就绪，请刷新页面")
                return
            logger.info("[WebUI] 未找到可用内置 dist，后台拉取静态资源")
            url = (plugin_config.pallas_webui_dist_zip_url or "").strip()
            url_candidates: list[str] = []
            resolve_err = ""
            selected: dict[str, object] = {}
            selected_tag = ""
            if not url:
                try:
                    repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "")
                    asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "")
                    tag = str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or "")
                    selected = await resolve_webui_release_for_runtime(repo, asset, tag, token=tok)
                    url = str(selected.get("asset_url", "") or "").strip()
                    url_candidates = [url] if url else []
                    selected_tag = str(selected.get("tag", "") or "").strip()
                except Exception as e:
                    resolve_err = format_exception_for_log(e)
                    url = ""
                    url_candidates = []
            else:
                url_candidates = [url]
            if not url:
                if resolve_err:
                    logger.error("[WebUI] 无法解析 WebUI 下载地址 ({})", resolve_err)
                else:
                    logger.error("[WebUI] 无法解析 WebUI 下载地址")
                return
            errors: list[str] = []
            succeeded_url = ""
            for candidate in url_candidates or [url]:
                try:
                    selected_commit = str(selected.get("bot_commit", "") or "").strip() or None
                    await download_and_extract_dist_zip(
                        public,
                        candidate,
                        require_compatible_manifest=True,
                        github_token=tok,
                        current_commit=selected_commit,
                    )
                    succeeded_url = candidate
                    errors.clear()
                    break
                except Exception as e:
                    err_msg = format_exception_for_log(e)
                    errors.append(f"{candidate} -> {err_msg}")
            if errors:
                logger.error("[WebUI] dist 下载/解压失败: {}", " | ".join(errors))
                register_startup_warning("console", "dist-bootstrap-failed")
            elif succeeded_url:
                try:
                    save_installed_webui_version(selected_tag, succeeded_url)
                except Exception:
                    pass
                logger.info("[WebUI] 静态资源就绪，请刷新页面")
            webui_ver = get_webui_dist_version() or get_installed_webui_version().get("tag", "")
            set_console_meta({"static_root": str(public), "http_base": base, "version": webui_ver})

        async def background_release_checks() -> None:
            tok = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
            try:
                repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or DEFAULT_WEBUI_DIST_ZIP_REPO)
                asset_chk = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "dist.zip")
                requested_tag = str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or "")
                installed = get_installed_webui_version()
                current_tag = str(installed.get("tag", "") or "").strip()
                latest_info = await resolve_webui_release_for_runtime(repo, asset_chk, requested_tag, token=tok)
                latest_tag = str(latest_info.get("tag", "") or "").strip()
                if webui_has_release_update(latest_tag=latest_tag, current_tag=current_tag):
                    release_url = str(latest_info.get("html_url", "") or "").strip()
                    logger.info(
                        "[WebUI] WebUI update available {} (current {}){}",
                        latest_tag,
                        current_tag or "-",
                        f" → {release_url}" if release_url else "",
                    )
                else:
                    logger.debug(
                        "[WebUI] WebUI up to date or incomparable tag={} latest={}",
                        current_tag or "-",
                        latest_tag or "-",
                    )
            except Exception as e:
                logger.debug("[WebUI] WebUI update check failed: {}", format_exception_for_log(e))
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
                        "[WebUI] Bot update available {} (current {}){}",
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
                        "[WebUI] Bot development build is ahead of release [{}] at commit [{}]",
                        bot_latest_tag,
                        bot_current_commit or "-",
                    )
                elif bot_current_tag:
                    logger.debug("[WebUI] Bot is up to date at tag [{}]", bot_current_tag)
                else:
                    logger.debug("[WebUI] Bot is running commit [{}]", bot_current_commit or "-")
            except Exception as e:
                logger.debug("[WebUI] Bot update check failed: {}", format_exception_for_log(e))

        async def guarded(name: str, fn):
            try:
                await fn()
            except Exception as e:
                logger.error("[WebUI] 后台任务 {} 异常: {}", name, format_exception_for_log(e))

        async def warm_plugin_store_assets() -> None:
            from pallas.console.webui.plugin_store_assets import refresh_store_asset_snapshot

            await refresh_store_asset_snapshot()

        if not check_webui_exists(public):
            register_startup_scheduled("控制台静态资源", "task=bootstrap")
            asyncio.create_task(guarded("webui-dist-bootstrap", bootstrap_webui_dist))
        else:
            register_startup_ready("控制台静态资源", f"前端栈 [{frontend}]")
        asyncio.create_task(guarded("release-version-check", background_release_checks))
        asyncio.create_task(guarded("console-read-cache-warm", warm_console_read_caches))
        asyncio.create_task(guarded("plugin-store-assets-warm", warm_plugin_store_assets))
