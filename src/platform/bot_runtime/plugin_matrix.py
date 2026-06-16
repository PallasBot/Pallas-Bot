"""4.0 core / extra 插件矩阵，见 docs/architecture/pallas-4.0-slim.md。"""

from __future__ import annotations

import importlib.util

# core：保留在本体 src/plugins/（默认 slim 加载）
CORE_PLUGIN_NAMES: frozenset[str] = frozenset({
    "repeater",
    "help",
    "pallas_webui",
    "ingress_gate",
    "bot_status",
    "callback",
    "request_handler",
    "blacklist",
    "block",
    "pallas_console_metrics",
    "connectivity",
})

# 分片内置能力：仍在 src/plugins/，非用户可选扩展；后续内核化见 pallas-4.0-slim.md
SHARD_INTERNAL_PLUGIN_NAMES: frozenset[str] = frozenset({
    "pallas_console_metrics",
    "relogin_forward",
    "maa_hub",
    "ingress_gate",
})

# extra：迁出为 pip 扩展包
EXTRA_PLUGIN_PACKAGES: dict[str, str] = {
    "pallas_protocol": "pallas-plugin-protocol",
    "relogin_bot": "pallas-plugin-protocol",
    "relogin_forward": "pallas-plugin-protocol",
    "duel": "pallas-plugin-duel",
    "who_is_spy": "pallas-plugin-who-is-spy",
    "roulette": "pallas-plugin-party",
    "drink": "pallas-plugin-party",
    "dream": "pallas-plugin-dream",
    "maa": "pallas-plugin-maa",
    "maa_hub": "pallas-plugin-maa",
    "draw": "pallas-plugin-draw",
    "sing": "pallas-plugin-ai-media",
    "chat": "pallas-plugin-ai-media",
    "greeting": "pallas-plugin-social",
    "take_name": "pallas-plugin-social",
    "community_stats": "pallas-plugin-community-stats",
    "ollama": "pallas-plugin-ollama",
}

# pip 包 → NoneBot 模块（已安装时由 plugin_loader 按角色加载）
EXTRA_PACKAGE_MODULES: dict[str, tuple[str, ...]] = {
    "pallas-plugin-protocol": (
        "pallas_plugin_protocol",
        "pallas_plugin_relogin_bot",
        "pallas_plugin_relogin_forward",
    ),
    "pallas-plugin-duel": ("pallas_plugin_duel",),
    "pallas-plugin-maa": ("pallas_plugin_maa", "pallas_plugin_maa_hub"),
    "pallas-plugin-who-is-spy": ("pallas_plugin_who_is_spy",),
    "pallas-plugin-party": ("pallas_plugin_roulette", "pallas_plugin_drink"),
    "pallas-plugin-dream": ("pallas_plugin_dream",),
    "pallas-plugin-draw": ("pallas_plugin_draw",),
    "pallas-plugin-ai-media": ("pallas_plugin_sing", "pallas_plugin_chat"),
    "pallas-plugin-social": ("pallas_plugin_greeting", "pallas_plugin_take_name"),
    "pallas-plugin-community-stats": ("pallas_plugin_community_stats",),
    "pallas-plugin-ollama": ("pallas_plugin_ollama",),
}

EXTRA_PLUGIN_NAMES: frozenset[str] = frozenset(EXTRA_PLUGIN_PACKAGES.keys())

EXTRA_PACKAGE_PRIORITY: dict[str, str] = {
    "pallas-plugin-protocol": "P0",
    "pallas-plugin-duel": "P0",
    "pallas-plugin-who-is-spy": "P0",
    "pallas-plugin-maa": "P0",
    "pallas-plugin-party": "P1",
    "pallas-plugin-dream": "P1",
    "pallas-plugin-draw": "P1",
    "pallas-plugin-ai-media": "P1",
    "pallas-plugin-social": "P2",
    "pallas-plugin-community-stats": "P2",
    "pallas-plugin-ollama": "P2",
}

# 已迁出独立仓的官方扩展（pip 包名 → 仓库根 URL）
OFFICIAL_EXTENSION_REPOS: dict[str, str] = {
    "pallas-plugin-protocol": "https://github.com/TogetsuDo/pallas-plugin-protocol",
    "pallas-plugin-duel": "https://github.com/TogetsuDo/pallas-plugin-duel",
    "pallas-plugin-maa": "https://github.com/TogetsuDo/pallas-plugin-maa",
    "pallas-plugin-who-is-spy": "https://github.com/TogetsuDo/pallas-plugin-who-is-spy",
    "pallas-plugin-dream": "https://github.com/TogetsuDo/pallas-plugin-dream",
    "pallas-plugin-party": "https://github.com/TogetsuDo/pallas-plugin-party",
    "pallas-plugin-draw": "https://github.com/TogetsuDo/pallas-plugin-draw",
    "pallas-plugin-ai-media": "https://github.com/TogetsuDo/pallas-plugin-ai-media",
    "pallas-plugin-social": "https://github.com/TogetsuDo/pallas-plugin-social",
    "pallas-plugin-community-stats": "https://github.com/TogetsuDo/pallas-plugin-community-stats",
    "pallas-plugin-ollama": "https://github.com/TogetsuDo/pallas-plugin-ollama",
}

_PROTOCOL_MODULE_NAMES: frozenset[str] = frozenset({
    "src.plugins.pallas_protocol",
    "pallas_plugin_protocol",
})


def uv_extra_for_package(package: str) -> str:
    short = (package or "").strip().removeprefix("pallas-plugin-")
    return f"plugins-{short}" if short else ""


def uv_extra_for_plugin(name: str) -> str | None:
    pkg = extra_package_for_plugin(name)
    if not pkg:
        return None
    extra = uv_extra_for_package(pkg)
    return extra or None


def is_core_plugin(name: str) -> bool:
    return (name or "").strip() in CORE_PLUGIN_NAMES


def is_extra_plugin(name: str) -> bool:
    return (name or "").strip() in EXTRA_PLUGIN_NAMES


def is_shard_internal_plugin(name: str) -> bool:
    return (name or "").strip() in SHARD_INTERNAL_PLUGIN_NAMES


def extra_package_for_plugin(name: str) -> str | None:
    return EXTRA_PLUGIN_PACKAGES.get((name or "").strip())


def official_extension_repo_url(package: str) -> str | None:
    return OFFICIAL_EXTENSION_REPOS.get((package or "").strip())


def should_load_bundled_plugin(name: str, *, load_bundled_extra: bool) -> bool:
    short = (name or "").strip()
    if not short:
        return False
    if is_core_plugin(short):
        return True
    if is_extra_plugin(short):
        return load_bundled_extra
    return True


def pip_module_installed(module_path: str) -> bool:
    root = (module_path or "").strip().split(".", 1)[0]
    if not root:
        return False
    return importlib.util.find_spec(root) is not None


PIP_MODULE_LOAD_ROLE: dict[str, str] = {
    "pallas_plugin_protocol": "hub",
    "pallas_plugin_relogin_bot": "hub",
    "pallas_plugin_relogin_forward": "worker",
    "pallas_plugin_maa_hub": "hub",
    "pallas_plugin_community_stats": "hub",
}


def installed_extra_plugin_modules(*, hub: bool | None = None) -> list[str]:
    """已安装的 pip 扩展模块。hub=True/False 按角色过滤；None 为 unified 加载全部已安装项。"""
    out: list[str] = []
    seen: set[str] = set()
    for modules in EXTRA_PACKAGE_MODULES.values():
        for mod in modules:
            if mod in seen or not pip_module_installed(mod):
                continue
            if hub is not None:
                load_role = PIP_MODULE_LOAD_ROLE.get(mod, "both")
                role = "hub" if hub else "worker"
                if load_role != "both" and load_role != role:
                    continue
            seen.add(mod)
            out.append(mod)
    return out


def resolve_hub_bundled_module_paths(*, load_bundled_extra: bool | None = None) -> list[str]:
    from src.foundation.config.repo_settings import read_bootstrap_load_bundled_extra_plugins
    from src.platform.bot_runtime.roles import HUB_PLUGIN_MODULES

    if load_bundled_extra is None:
        load_bundled_extra = read_bootstrap_load_bundled_extra_plugins()
    out: list[str] = []
    for mod in HUB_PLUGIN_MODULES:
        short = mod.rsplit(".", 1)[-1]
        if is_extra_plugin(short) and not load_bundled_extra:
            continue
        out.append(mod)
    return out


def protocol_plugin_loaded() -> bool:
    from nonebot import get_loaded_plugins

    for p in get_loaded_plugins():
        mod = getattr(p, "module", None)
        mname = getattr(mod, "__name__", "")
        if mname in _PROTOCOL_MODULE_NAMES:
            return True
    return False


def protocol_extension_status() -> dict[str, str | bool | None]:
    pkg = "pallas-plugin-protocol"
    uv_extra = uv_extra_for_package(pkg)
    return {
        "installed": protocol_plugin_loaded(),
        "package": pkg,
        "uv_extra": uv_extra,
        "install_cli": f"uv sync --extra {uv_extra}" if uv_extra else None,
        "repository_url": official_extension_repo_url(pkg),
    }
