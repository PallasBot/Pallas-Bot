"""按 reload_policy 执行插件重载（元数据索引 / 模块尝试）。"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from nonebot import logger

from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package
from pallas.core.platform.plugin_runtime.resolve import loaded_plugin_module_prefix
from pallas.core.plugin_reload.metadata_index import (
    reload_plugin_metadata_index,
    reload_policy_for_plugin_name,
)

if TYPE_CHECKING:
    from pallas.core.plugin_reload.metadata import ReloadPolicy


class PluginReloadError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def try_reload_plugin_module(plugin_id: str) -> bool:
    prefix = loaded_plugin_module_prefix(plugin_id)
    if not prefix:
        return False
    try:
        mod = importlib.import_module(prefix)
        importlib.reload(mod)
        return True
    except Exception as e:
        logger.warning("plugin {} module reload failed: {}", plugin_id, e)
        return False


def execute_plugin_reload(plugin_name: str) -> dict[str, Any]:
    canonical = canonical_plugin_package((plugin_name or "").strip())
    if not canonical:
        raise PluginReloadError("缺少插件名")

    policy: ReloadPolicy = reload_policy_for_plugin_name(canonical)
    result: dict[str, Any] = {
        "plugin": canonical,
        "reload_policy": policy,
        "action": "none",
        "ok": True,
        "message": "",
    }

    if policy == "config_only":
        result["action"] = "config-only-hint"
        result["message"] = f"插件 {canonical} 为 config_only 策略；请通过 WebUI 插件页保存配置即可热载，无需 reload。"
        return result

    if loaded_plugin_module_prefix(canonical) is None:
        result["ok"] = False
        result["message"] = f"插件 {canonical} 未加载或 Bot 未运行；请确认插件已启用，或重启 Bot 后重试。"
        return result

    reload_plugin_metadata_index()
    result["action"] = "metadata-reload"
    result["message"] = f"插件 {canonical}：已重建元数据索引（ingress/help/storage）。"

    if policy != "full":
        return result

    if try_reload_plugin_module(canonical):
        result["action"] = "full-reload"
        result["message"] = (
            f"插件 {canonical}：已重建元数据索引并尝试重载模块。"
            " matcher 级热卸载仍受消息框架限制，若行为异常请重启 Bot。"
        )
        return result

    result["ok"] = False
    result["action"] = "metadata-only"
    result["message"] = f"插件 {canonical}：元数据索引已重建，但代码级重载未成功，请重启 Bot。"
    return result
