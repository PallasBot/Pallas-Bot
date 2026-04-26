# ruff: noqa: E501
from nonebot import get_app, get_driver, get_plugin_config, logger
from nonebot.plugin import PluginMetadata

from src.common.web import public_base_url

from .api import register_api
from .config import Config
from .extended_api import register_extended_api, set_console_meta
from .manager import (
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
    name="Pallas 控制台",
    description="提供 Pallas 控制台页面与扩展 API。",
    usage="""
浏览器入口：
/pallas/

核心接口：
/pallas/api/health
/pallas/api/system
/pallas/api/instances
/pallas/api/logs
/pallas/api/db/overview
/pallas/api/message-stats
""".strip(),
    type="application",
    homepage="https://github.com/PallasBot/Pallas-Bot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "3.0.0",
        "menu_data": [
            {
                "func": "控制台页面",
                "trigger_method": "http",
                "trigger_condition": "/pallas/",
                "brief_des": "提供控制台界面",
                "detail_des": "展示实例状态、日志、数据库与插件信息。",
            },
            {
                "func": "扩展状态接口",
                "trigger_method": "http",
                "trigger_condition": "/pallas/api/*",
                "brief_des": "提供控制台数据接口",
                "detail_des": "提供 health、system、instances、logs、message-stats 等接口。",
            },
        ],
    },
)

plugin_config = get_plugin_config(Config)
app = get_app()
driver = get_driver()

# 启用控制台跨域访问
if plugin_config.pallas_webui_enabled and plugin_config.pallas_webui_cors:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@driver.on_startup
async def _pallas_webui_startup() -> None:
    if not plugin_config.pallas_webui_enabled:
        return
    public = webui_public_path()
    url = (plugin_config.pallas_webui_dist_zip_url or "").strip()
    url_candidates: list[str] = []
    if not url:
        # 自动解析发布资产下载地址
        try:
            repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "")
            asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "")
            tag = str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or "")
            url_candidates = await resolve_github_release_asset_urls(repo, asset, tag)
            url = github_release_asset_url(
                str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or ""),
                str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or ""),
                str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or ""),
            )
        except Exception:
            url = ""
            url_candidates = []
    elif url:
        url_candidates = [url]
    if url and not check_webui_exists(public):
        errors: list[str] = []
        succeeded_url = ""
        for candidate in url_candidates or [url]:
            try:
                await download_and_extract_dist_zip(public, candidate)
                succeeded_url = candidate
                errors.clear()
                break
            except Exception as e:
                errors.append(f"{candidate} -> {e}")
        if errors:
            logger.error("Pallas 控制台: 下载或解压 dist zip 失败，已尝试: %s", " | ".join(errors))
        elif succeeded_url:
            # 记录已安装版本
            try:
                tag = str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or "").strip()
                if not tag:
                    try:
                        repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "")
                        info = await fetch_latest_webui_release(repo)
                        tag = info.get("tag", "")
                    except Exception:
                        tag = ""
                save_installed_webui_version(tag, succeeded_url)
            except Exception:
                pass
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
    set_console_meta({"static_root": str(public), "http_base": base, "version": webui_version})
    register_extended_api(app, api_base=api_base, plugin_config=plugin_config)
    register_routes(app, public_dir=public, base=base)
    dconf = get_driver().config
    open_base = public_base_url(
        host=getattr(dconf, "host", None),
        port=getattr(dconf, "port", None),
    )
    logger.info(f"Pallas 控制台 | WebUI={open_base}{base}/")
    # 启动时检查 WebUI 更新
    try:
        repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "PallasBot/Pallas-Bot-WebUI")
        installed = get_installed_webui_version()
        current_tag = str(installed.get("tag", "") or "").strip()
        latest_info = await fetch_latest_webui_release(repo)
        latest_tag = str(latest_info.get("tag", "") or "").strip()
        if latest_tag and current_tag != latest_tag:
            release_url = str(latest_info.get("html_url", "") or "").strip()
            logger.info(
                f"Pallas 控制台: 发现新版本 WebUI {latest_tag}（当前: {current_tag or '未知'}）"
                + (f" → {release_url}" if release_url else "")
                + "，可在控制台更新页面一键更新"
            )
        else:
            logger.info(f"Pallas 控制台: WebUI 已是最新版本（{current_tag or '未知'}）")
    except Exception as _upd_err:
        logger.debug(f"Pallas 控制台: 检查 WebUI 更新失败: {_upd_err}")
    # 启动时检查 Bot 更新
    try:
        bot_current = get_bot_current_version()
        bot_current_tag = bot_current.get("tag", "")
        bot_current_commit = bot_current.get("commit", "")
        bot_latest_info = await fetch_latest_bot_release("PallasBot/Pallas-Bot")
        bot_latest_tag = str(bot_latest_info.get("tag", "") or "").strip()
        if bot_latest_tag and bot_current_tag and bot_current_tag != bot_latest_tag:
            bot_release_url = str(bot_latest_info.get("html_url", "") or "").strip()
            logger.info(
                f"Pallas 控制台: 发现新版本 Bot {bot_latest_tag}（当前: {bot_current_tag}）"
                + (f" → {bot_release_url}" if bot_release_url else "")
                + "，可在控制台查看更新"
            )
        elif bot_current_tag:
            logger.info(f"Pallas 控制台: Bot 已是最新版本（{bot_current_tag}）")
        else:
            logger.info(f"Pallas 控制台: Bot under development,commit={bot_current_commit or '未知'}")
    except Exception as _bot_upd_err:
        logger.debug(f"Pallas 控制台: 检查 Bot 更新失败: {_bot_upd_err}")
