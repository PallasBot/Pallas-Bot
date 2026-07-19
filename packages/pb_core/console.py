"""控制台地址与插件矩阵摘要。"""

from __future__ import annotations

from nonebot import get_driver, logger

from pallas.console.web import public_base_url
from pallas.core.platform.bot_runtime.plugin_matrix import (
    CORE_PLUGIN_NAMES,
    EXTRA_PLUGIN_NAMES,
    extra_package_for_plugin,
    is_core_plugin,
)


def format_console_hint_text() -> str:
    try:
        from packages.pb_webui.config import get_config as get_webui_config

        cfg = get_webui_config()
        if not cfg.pallas_webui_enabled:
            return "网页控制台已在本实例关闭（pallas_webui_enabled=false）。"
    except ImportError:
        cfg = None
    except Exception:
        logger.exception("pb_core: 读取 WebUI 配置失败")
        cfg = None

    driver = get_driver()
    base = public_base_url(host=driver.config.host, port=driver.config.port)
    path = ""
    if cfg is not None:
        path = (cfg.pallas_webui_http_base or "/pallas").strip()
        if path and not path.startswith("/"):
            path = f"/{path}"
    url = f"{base.rstrip('/')}{path or '/pallas'}/"
    return f"控制台：{url}\n浏览器打开后使用启动日志中的口令登录。"


def format_plugins_summary_text(*, loaded_names: set[str]) -> str:
    core = sorted(name for name in loaded_names if is_core_plugin(name))
    extra = sorted(name for name in loaded_names if name in EXTRA_PLUGIN_NAMES)
    lines = [
        f"已加载 core 插件 {len(core)}：{', '.join(core) if core else '（无）'}",
        f"已加载 extra 插件 {len(extra)}：{', '.join(extra) if extra else '（无）'}",
        f"core 全集 {len(CORE_PLUGIN_NAMES)} · extra 全集 {len(EXTRA_PLUGIN_NAMES)}",
    ]
    missing_core = sorted(CORE_PLUGIN_NAMES - loaded_names)
    if missing_core:
        lines.append(f"未加载 core：{', '.join(missing_core)}")
    if extra:
        packs = sorted({extra_package_for_plugin(name) for name in extra if extra_package_for_plugin(name)})
        if packs:
            lines.append(f"对应扩展包：{', '.join(packs)}")
    lines.append("安装扩展：WebUI 插件页，或 uv run pallas ext install <package>。")
    return "\n".join(lines)
