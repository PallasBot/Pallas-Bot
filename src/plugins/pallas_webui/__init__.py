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
    github_release_asset_url,
    resolve_github_release_asset_urls,
    webui_public_path,
)
from .public import register_routes

__plugin_meta__ = PluginMetadata(
    name="Pallas 控制台",
    description="独立 Web 构建产物 + JSON API：静态资源目录 data/pallas_webui/public 与路径前缀 /pallas/api。",
    usage="""将 Vite/ Vue 等 dist 放入 data/pallas_webui/public，或配置 pallas_webui_dist_zip_url 拉取。
浏览器: /pallas/ ；API: /pallas/api/health, /system, /plugins, /bots, /logs, /db/overview,
/db/mongodb/aggregate（须配置 pallas_webui_api_token）, /instances, /bot-configs, /group-configs,
/friend-requests, /friend-list 等
""".strip(),
    type="application",
    homepage="https://github.com/PallasBot/Pallas-Bot",
    extra={"version": "0.1.0"},
)

plugin_config = get_plugin_config(Config)
app = get_app()
driver = get_driver()

# 便于本地用独立 dev server（Vite）与 Bot 进程分离调试时跨域
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
        # URL 留空时先查 GitHub release 资产列表再选，减少环境里硬编码版本地址。
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
        for candidate in (url_candidates or [url]):
            try:
                await download_and_extract_dist_zip(public, candidate)
                errors.clear()
                break
            except Exception as e:
                errors.append(f"{candidate} -> {e}")
        if errors:
            logger.error("Pallas 控制台: 下载或解压 dist zip 失败，已尝试: %s", " | ".join(errors))
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
    set_console_meta({"static_root": str(public), "http_base": base})
    register_extended_api(app, api_base=api_base, plugin_config=plugin_config)
    register_routes(app, public_dir=public, base=base)
    dconf = get_driver().config
    open_base = public_base_url(
        host=getattr(dconf, "host", None),
        port=getattr(dconf, "port", None),
    )
    logger.info(
        f"Pallas 控制台: 浏览器 {open_base}{base}/ · API {api_base} · public={public}",
    )
