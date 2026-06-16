"""4.0 core / extra 插件矩阵，见 docs/architecture/pallas-4.0-slim.md。"""

from __future__ import annotations

# core：保留在本体 src/plugins/
CORE_PLUGIN_NAMES: frozenset[str] = frozenset({
    "repeater",
    "help",
    "pallas_webui",
    "pallas_protocol",
    "ingress_gate",
    "bot_status",
    "callback",
    "request_handler",
    "blacklist",
    "block",
    "pallas_console_metrics",
    "relogin_bot",
    "relogin_forward",
    "connectivity",
})

# extra：迁出为 pip 扩展包
EXTRA_PLUGIN_PACKAGES: dict[str, str] = {
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

EXTRA_PLUGIN_NAMES: frozenset[str] = frozenset(EXTRA_PLUGIN_PACKAGES.keys())

EXTRA_PACKAGE_PRIORITY: dict[str, str] = {
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


def extra_package_for_plugin(name: str) -> str | None:
    return EXTRA_PLUGIN_PACKAGES.get((name or "").strip())


def should_load_bundled_plugin(name: str, *, load_bundled_extra: bool) -> bool:
    short = (name or "").strip()
    if not short:
        return False
    if is_core_plugin(short):
        return True
    if is_extra_plugin(short):
        return load_bundled_extra
    return True
