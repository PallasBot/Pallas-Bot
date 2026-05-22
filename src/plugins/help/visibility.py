from __future__ import annotations

import json

from src.common.paths import plugin_data_dir

_VISIBILITY_FILE = "help_visibility.json"

# 始终不出现在普通帮助总览与「开启/关闭全部」范围内
BUILTIN_HELP_HIDDEN_PLUGINS = frozenset({
    "pallas_webui",
    "pallas_protocol",
    "_ingress_gate",
    "pallas_console_metrics",
})


def resolve_console_stats_excluded_plugin_names() -> frozenset[str]:
    """控制台 Matcher 插件次数统计排除名单（小写键名，含 claim 别名 ingress_gate）。"""
    names = set(BUILTIN_HELP_HIDDEN_PLUGINS)
    names.add("ingress_gate")
    return frozenset(str(n).strip().lower() for n in names if str(n).strip())


def _visibility_path():
    return plugin_data_dir("help") / _VISIBILITY_FILE


def resolve_help_ignored_plugins() -> list[str]:
    try:
        from .config import get_help_config

        cfg = get_help_config()
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
