"""core / extra 插件矩阵。"""

from __future__ import annotations

import importlib.util
import re
from typing import Literal

from pallas.core.foundation.paths import PROJECT_ROOT

ActivationPolicy = Literal["hot-reloadable", "workers-restart", "full-restart"]

CORE_PLUGIN_NAMES: frozenset[str] = frozenset({
    "pb_core",
    "repeater",
    "help",
    "pb_webui",
    "request_handler",
    "blacklist",
    "drink",
    "greeting",
    "roulette",
    "take_name",
    "llm_chat",
    "pb_stats",
})

SHARD_INTERNAL_PLUGIN_NAMES: frozenset[str] = frozenset({
    "relogin_forward",
    "maa_hub",
})

EXTRA_PLUGIN_PACKAGES: dict[str, str] = {
    "pb_protocol": "pallas-plugin-protocol",
    "relogin_bot": "pallas-plugin-protocol",
    "relogin_forward": "pallas-plugin-protocol",
    "duel": "pallas-plugin-duel",
    "who_is_spy": "pallas-plugin-who-is-spy",
    "dream": "pallas-plugin-dream",
    "maa": "pallas-plugin-maa",
    "maa_hub": "pallas-plugin-maa",
    "draw": "pallas-plugin-draw",
    "sing": "pallas-plugin-ai-media",
    "chat": "pallas-plugin-ai-media",
    "bot_status": "pallas-plugin-bot-status",
}

EXTRA_PACKAGE_MODULES: dict[str, tuple[str, ...]] = {
    "pallas-plugin-protocol": (
        "pallas_plugin_protocol",
        "pallas_plugin_relogin_bot",
        "pallas_plugin_relogin_forward",
    ),
    "pallas-plugin-duel": ("pallas_plugin_duel",),
    "pallas-plugin-maa": ("pallas_plugin_maa", "pallas_plugin_maa_hub"),
    "pallas-plugin-who-is-spy": ("pallas_plugin_who_is_spy",),
    "pallas-plugin-dream": ("pallas_plugin_dream",),
    "pallas-plugin-draw": ("pallas_plugin_draw",),
    "pallas-plugin-ai-media": ("pallas_plugin_sing", "pallas_plugin_chat"),
    "pallas-plugin-bot-status": ("pallas_plugin_bot_status",),
}

EXTRA_PLUGIN_NAMES: frozenset[str] = frozenset(EXTRA_PLUGIN_PACKAGES.keys())

EXTRA_PACKAGE_PRIORITY: dict[str, str] = {
    "pallas-plugin-protocol": "P0",
    "pallas-plugin-duel": "P0",
    "pallas-plugin-who-is-spy": "P0",
    "pallas-plugin-maa": "P0",
    "pallas-plugin-dream": "P1",
    "pallas-plugin-draw": "P1",
    "pallas-plugin-ai-media": "P1",
    "pallas-plugin-bot-status": "P2",
}

OFFICIAL_EXTENSION_REPOS: dict[str, str] = {
    "pallas-plugin-protocol": "https://github.com/TogetsuDo/pallas-plugin-protocol",
    "pallas-plugin-duel": "https://github.com/TogetsuDo/pallas-plugin-duel",
    "pallas-plugin-maa": "https://github.com/TogetsuDo/pallas-plugin-maa",
    "pallas-plugin-who-is-spy": "https://github.com/TogetsuDo/pallas-plugin-who-is-spy",
    "pallas-plugin-dream": "https://github.com/TogetsuDo/pallas-plugin-dream",
    "pallas-plugin-draw": "https://github.com/TogetsuDo/pallas-plugin-draw",
    "pallas-plugin-ai-media": "https://github.com/TogetsuDo/pallas-plugin-ai-media",
    "pallas-plugin-bot-status": "https://github.com/TogetsuDo/pallas-plugin-bot-status",
}

OFFICIAL_EXTENSION_ACTIVATION_POLICY: dict[str, ActivationPolicy] = {
    "pallas-plugin-protocol": "full-restart",
    "pallas-plugin-duel": "workers-restart",
    "pallas-plugin-maa": "full-restart",
    "pallas-plugin-who-is-spy": "workers-restart",
    "pallas-plugin-dream": "workers-restart",
    "pallas-plugin-draw": "hot-reloadable",
    "pallas-plugin-ai-media": "workers-restart",
    "pallas-plugin-bot-status": "hot-reloadable",
}

# 与扩展仓 PluginMetadata.name / 文档标题一致（插件商店卡片主标题）
OFFICIAL_EXTENSION_TITLES: dict[str, str] = {
    "pallas-plugin-duel": "牛牛决斗",
    "pallas-plugin-draw": "牛牛画画",
    "pallas-plugin-dream": "牛牛做梦",
    "pallas-plugin-maa": "MAA 远控",
    "pallas-plugin-protocol": "协议端管理",
    "pallas-plugin-who-is-spy": "谁是卧底",
    "pallas-plugin-ai-media": "唱歌 / 酒后聊天",
    "pallas-plugin-bot-status": "牛牛状态",
}

# 与扩展仓 README 首段说明一致（插件商店卡片单行描述）
OFFICIAL_EXTENSION_DESCRIPTIONS: dict[str, str] = {
    "pallas-plugin-duel": "牛牛决斗。",
    "pallas-plugin-draw": "牛牛画画（AI 生图网关）。",
    "pallas-plugin-dream": "牛牛做梦（群内旁路、分片漂移）。",
    "pallas-plugin-maa": "MAA 远控（含 worker 插件 pallas_plugin_maa 与分片 hub 入口 pallas_plugin_maa_hub）。",
    "pallas-plugin-protocol": "协议端管理（NapCat / SnowLuma）与 牛牛重新上号（含分片 worker 转发）。",
    "pallas-plugin-who-is-spy": "谁是卧底。",
    "pallas-plugin-ai-media": "唱歌（sing）与 酒后聊天（chat）。",
    "pallas-plugin-bot-status": "牛牛状态（在吗、报数、离线邮件）。",
}

OFFICIAL_EXTENSION_README_PATHS: dict[str, str] = {
    "pallas-plugin-protocol": "docs/plugins/pb_protocol/README.md",
    "pallas-plugin-duel": "docs/plugins/duel/README.md",
    "pallas-plugin-maa": "docs/plugins/maa/README.md",
    "pallas-plugin-who-is-spy": "docs/plugins/who_is_spy/README.md",
    "pallas-plugin-dream": "docs/plugins/dream/README.md",
    "pallas-plugin-draw": "docs/plugins/draw/README.md",
    "pallas-plugin-bot-status": "docs/plugins/bot_status/README.md",
}

_PROTOCOL_MODULE_NAMES: frozenset[str] = frozenset({
    "packages.pb_protocol",
    "pallas_plugin_protocol",
})

PLUGIN_BUNDLED_MODULE_PREFIXES: dict[str, str] = {
    **{name: f"packages.{name}" for name in CORE_PLUGIN_NAMES},
    "pb_protocol": "packages.pb_protocol",
    "relogin_bot": "packages.relogin_bot",
    "relogin_forward": "packages.relogin_forward",
    "maa_hub": "packages.maa_hub",
}

PLUGIN_LEGACY_ALIASES: dict[str, tuple[str, ...]] = {
    "pb_webui": ("pallas_webui",),
    "pb_protocol": ("pallas_protocol",),
    "pb_stats": ("community_stats", "pallas_plugin_community_stats"),
    "llm_chat": ("ollama", "pallas_plugin_llm_chat"),
}


def uv_extra_for_package(package: str) -> str:
    short = (package or "").strip().removeprefix("pallas-plugin-")
    return f"plugins-{short}" if short else ""


def ext_install_cli_for_package(package: str) -> str | None:
    pkg = (package or "").strip()
    if not pkg:
        return None
    return f"uv run pallas ext install {pkg}"


def uv_extra_for_plugin(name: str) -> str | None:
    pkg = extra_package_for_plugin(name)
    if not pkg:
        return None
    extra = uv_extra_for_package(pkg)
    return extra or None


def is_core_plugin(name: str) -> bool:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    return canonical_plugin_package((name or "").strip()) in CORE_PLUGIN_NAMES


def is_extra_plugin(name: str) -> bool:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    return canonical_plugin_package((name or "").strip()) in EXTRA_PLUGIN_NAMES


def is_shard_internal_plugin(name: str) -> bool:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    return canonical_plugin_package((name or "").strip()) in SHARD_INTERNAL_PLUGIN_NAMES


def extra_package_for_plugin(name: str) -> str | None:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    return EXTRA_PLUGIN_PACKAGES.get(canonical_plugin_package((name or "").strip()))


def official_extension_repo_url(package: str) -> str | None:
    return OFFICIAL_EXTENSION_REPOS.get((package or "").strip())


_OFFICIAL_EXTENSION_REPO_OWNER = "TogetsuDo"
_OFFICIAL_EXTENSION_DEFAULT_REF = "main"
_OFFICIAL_EXTENSION_BRAND_AVATAR_PATH = "assets/brand-avatar.png"
_README_CENTERED_PARAGRAPH_RE = re.compile(r"<p\s+align=[\"']center[\"']>(.*?)</p>", flags=re.IGNORECASE | re.DOTALL)
_README_HTML_TAG_RE = re.compile(r"<[^>]+>")
_README_WHITESPACE_RE = re.compile(r"\s+")


def github_repo_owner(repository_url: str | None) -> str | None:
    raw = (repository_url or "").strip()
    if not raw:
        return None
    match = re.match(r"(?:https?://|git@)github\.com[/:]([^/]+)/", raw, flags=re.IGNORECASE)
    if not match:
        return None
    owner = match.group(1).strip()
    return owner or None


def official_extension_cover(package: str) -> str | None:
    pkg = (package or "").strip()
    return official_extension_asset_url(pkg, _OFFICIAL_EXTENSION_BRAND_AVATAR_PATH)


def official_extension_readme_summary(package: str) -> str:
    path_str = OFFICIAL_EXTENSION_README_PATHS.get((package or "").strip())
    if not path_str:
        return ""
    path = PROJECT_ROOT / path_str
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    title_index = text.find("<h1")
    search_start = max(title_index, 0)
    for match in _README_CENTERED_PARAGRAPH_RE.finditer(text, search_start):
        raw = _README_HTML_TAG_RE.sub("", match.group(1))
        summary = _README_WHITESPACE_RE.sub(" ", raw).strip()
        if summary:
            return summary
    return ""


def official_extension_asset_url(package: str, asset_path: str) -> str | None:
    repo_url = official_extension_repo_url(package)
    if not repo_url:
        return None
    match = re.match(r"https://github\.com/([^/]+)/([^/]+?)/?$", repo_url, flags=re.IGNORECASE)
    if not match:
        return None
    owner = match.group(1).strip()
    repo = match.group(2).strip()
    if not owner or not repo:
        return None
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{_OFFICIAL_EXTENSION_DEFAULT_REF}/{asset_path}"


def official_extension_description(package: str) -> str:
    pkg = (package or "").strip()
    return official_extension_readme_summary(pkg) or OFFICIAL_EXTENSION_DESCRIPTIONS.get(pkg, "")


def official_extension_display_name(package: str) -> str:
    pkg = (package or "").strip()
    title = OFFICIAL_EXTENSION_TITLES.get(pkg, "").strip()
    if title:
        return title
    short = pkg.removeprefix("pallas-plugin-")
    return short or pkg


def official_extension_activation_policy(package: str) -> ActivationPolicy | None:
    return OFFICIAL_EXTENSION_ACTIVATION_POLICY.get((package or "").strip())


def activation_policy_for_plugin(name: str) -> ActivationPolicy | None:
    pkg = extra_package_for_plugin(name)
    if not pkg:
        return None
    return official_extension_activation_policy(pkg)


def official_extension_visuals(package: str) -> dict[str, str | None]:
    pkg = (package or "").strip()
    if pkg not in OFFICIAL_EXTENSION_REPOS:
        return {"icon": None, "cover": None, "avatar": None}
    cover = official_extension_cover(pkg)
    return {
        "icon": cover or "/pallas/assets/brand-avatar.png",
        "cover": cover,
        "avatar": None,
    }


def pip_extra_installed_for_plugin(name: str) -> bool:
    pkg = extra_package_for_plugin(name)
    if not pkg:
        return False
    for mod in EXTRA_PACKAGE_MODULES.get(pkg, ()):
        if pip_module_installed(mod):
            return True
    return False


def should_load_bundled_plugin(name: str, *, load_bundled_extra: bool | str | None = None) -> bool:
    from pallas.core.foundation.config.repo_settings import normalize_load_bundled_extra_mode
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    short = canonical_plugin_package((name or "").strip())
    if not short:
        return False
    if is_core_plugin(short):
        return True
    if is_extra_plugin(short):
        mode = normalize_load_bundled_extra_mode(load_bundled_extra)
        if mode == "true":
            return True
        if mode == "false":
            return False
        return not pip_extra_installed_for_plugin(short)
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
    "pallas_plugin_maa": "worker",
    "pallas_plugin_maa_hub": "hub",
}


def installed_extra_plugin_modules(*, hub: bool | None = None) -> list[str]:
    """已安装的 pip 扩展模块；hub 为 None 时不按角色过滤。"""
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


def resolve_hub_bundled_module_paths(*, load_bundled_extra: bool | str | None = None) -> list[str]:
    from pallas.core.foundation.config.repo_settings import normalize_load_bundled_extra_mode
    from pallas.core.platform.bot_runtime.roles import HUB_PLUGIN_MODULES

    mode = normalize_load_bundled_extra_mode(load_bundled_extra)
    out: list[str] = []
    for mod in HUB_PLUGIN_MODULES:
        short = mod.rsplit(".", 1)[-1]
        if is_extra_plugin(short) and not should_load_bundled_plugin(short, load_bundled_extra=mode):
            continue
        if importlib.util.find_spec(mod) is None:
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
        "install_cli": ext_install_cli_for_package(pkg),
        "activation_policy": official_extension_activation_policy(pkg),
        "repository_url": official_extension_repo_url(pkg),
    }
