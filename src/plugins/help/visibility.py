from __future__ import annotations

import json

from src.common.paths import plugin_data_dir

_VISIBILITY_FILE = "help_visibility.json"

# 帮助菜单默认忽略（不出现在总览；与 Config.ignored_plugins 默认一致）
DEFAULT_HELP_IGNORED_PLUGINS = [
    "nonebot-plugin-alconna",
    "nonebot_plugin_apscheduler",
    "nonebot_plugin_waiter",
    "uniseg",
    "callback",
    "block",
    "_ingress_gate",
]

# 始终不出现在普通帮助总览与「开启/关闭全部」范围内
BUILTIN_HELP_HIDDEN_PLUGINS = frozenset({
    "pallas_webui",
    "pallas_protocol",
    "_ingress_gate",
})

# 群内「关闭插件」不影响以下模块（基础设施）
PLUGIN_DISABLE_EXEMPT = frozenset({"help", "_ingress_gate"})


def _visibility_path():
    return plugin_data_dir("help") / _VISIBILITY_FILE


def resolve_help_ignored_plugins() -> list[str]:
    try:
        from nonebot import get_plugin_config

        from .config import Config

        cfg = get_plugin_config(Config)
        vals = list(getattr(cfg, "ignored_plugins", []) or [])
    except Exception:
        vals = []
    return [str(x).strip() for x in vals if str(x).strip()]


def load_help_hidden_plugins() -> list[str]:
    """从 data 读取的额外隐藏名单（WebUI 可编辑）；不含内置隐藏。"""
    path = _visibility_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    vals = raw.get("hidden_plugins", [])
    if not isinstance(vals, list):
        return []
    out = [str(x).strip() for x in vals if str(x).strip()]
    return sorted(set(out))


def resolve_help_hidden_plugins() -> list[str]:
    """帮助总览与批量开关使用的完整隐藏名单（内置 + 文件）。"""
    return sorted(BUILTIN_HELP_HIDDEN_PLUGINS | set(load_help_hidden_plugins()))


def save_help_hidden_plugins(hidden_plugins: list[str]) -> list[str]:
    out = sorted({str(x).strip() for x in hidden_plugins if str(x).strip()})
    path = _visibility_path()
    payload = {
        "hidden_plugins": out,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
