"""仓库插件目录：磁盘发现 + 分片加载角色（供 WebUI / 帮助）。"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path  # noqa: TC003
from typing import Any

from src.common.paths import PROJECT_ROOT

_PLUGINS_ROOT = PROJECT_ROOT / "src" / "plugins"

_INFRA_NAME_PREFIXES = (
    "nonebot",
    "nonebot_plugin",
    "nonebot-plugin",
    "uniseg",
)

_INFRA_EXACT = frozenset({
    "nonebot_plugin_waiter",
    "nonebot_plugin_apscheduler",
    "nonebot-plugin-apscheduler",
    "nonebot-plugin-alconna",
    "nonebot_plugin_alconna",
})


def discover_plugin_packages() -> list[str]:
    if not _PLUGINS_ROOT.is_dir():
        return []
    out: list[str] = []
    for entry in sorted(_PLUGINS_ROOT.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if not (entry / "__init__.py").is_file():
            continue
        out.append(entry.name)
    return out


def _parse_plugin_metadata_stub(init_path: Path) -> dict[str, Any] | None:
    try:
        text = init_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id != "__plugin_meta__":
                continue
            if not isinstance(node.value, ast.Call):
                continue
            meta: dict[str, Any] = {}
            for kw in node.value.keywords:
                key = kw.arg
                if not key or key in ("extra", "supported_adapters", "homepage"):
                    continue
                if key in ("name", "description", "usage", "type") and isinstance(kw.value, ast.Constant):
                    val = kw.value.value
                    if isinstance(val, str):
                        meta[key] = val
            if meta.get("name"):
                return meta
    return None


def package_load_role(package: str) -> str:
    from src.common.bot_runtime.roles import (
        HUB_PLUGIN_MODULES,
        WORKER_SKIP_PLUGIN_NAMES,
        is_sharding_active,
        is_unified_role,
    )

    if is_unified_role() or not is_sharding_active():
        return "both"
    if package.startswith("_"):
        return "worker" if package == "_ingress_gate" else "internal"
    hub_short = {m.rsplit(".", 1)[-1] for m in HUB_PLUGIN_MODULES}
    if package in WORKER_SKIP_PLUGIN_NAMES:
        return "hub"
    if package in hub_short:
        return "hub"
    return "worker"


def is_infrastructure_plugin_name(name: str, module_name: str) -> bool:
    n = (name or "").strip().lower()
    m = (module_name or "").strip().lower()
    if n in _INFRA_EXACT or m in _INFRA_EXACT:
        return True
    return any(n.startswith(p) or m.startswith(p) for p in _INFRA_NAME_PREFIXES)


def package_has_config_module(package: str) -> bool:
    return (_PLUGINS_ROOT / package / "config.py").is_file()


def _loaded_plugin_index() -> tuple[dict[str, Any], dict[str, Any]]:
    from nonebot import get_loaded_plugins

    by_nb_name: dict[str, Any] = {}
    by_package: dict[str, Any] = {}
    for p in get_loaded_plugins():
        nb = str(getattr(p, "name", "") or "").strip()
        if nb:
            by_nb_name[nb] = p
        mod = getattr(p, "module", None)
        module_name = getattr(mod, "__name__", "") if mod is not None else ""
        if not module_name:
            module_name = str(getattr(p, "module_name", "") or "")
        short = module_name.rsplit(".", 1)[-1] if module_name else ""
        if short:
            by_package[short] = p
        if nb:
            by_package.setdefault(nb, p)
    return by_nb_name, by_package


def metadata_to_dict(meta: object | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    d: dict[str, Any] = {
        "name": getattr(meta, "name", None),
        "description": (getattr(meta, "description", None) or "")[:2000],
        "usage": (getattr(meta, "usage", None) or "")[:4000],
    }
    ex = getattr(meta, "extra", None)
    if ex:
        d["extra"] = dict(ex) if isinstance(ex, dict) else ex
    typ = getattr(meta, "type", None)
    if typ is not None:
        d["type"] = str(typ)
    return d


def build_plugin_catalog_rows(
    *,
    ignored: set[str] | None = None,
    hidden: set[str] | None = None,
) -> list[dict[str, Any]]:
    """合并磁盘插件与当前进程已加载插件（含第三方基础设施）。"""
    ignored = ignored or set()
    hidden = hidden or set()
    _, by_package = _loaded_plugin_index()
    rows: list[dict[str, Any]] = []
    seen_packages: set[str] = set()

    def _help_flags(nb_name: str, package: str) -> tuple[bool, bool, bool]:
        ids = {nb_name, package, f"src.plugins.{package}"}
        ign = any(x in ignored for x in ids if x)
        hid = any(x in hidden for x in ids if x)
        visible = not ign and not hid
        return visible, ign, hid

    for package in discover_plugin_packages():
        seen_packages.add(package)
        init_path = _PLUGINS_ROOT / package / "__init__.py"
        stub = _parse_plugin_metadata_stub(init_path)
        loaded = package in by_package
        p = by_package.get(package)
        nb_name = str(getattr(p, "name", "") or "") if p is not None else package
        module_name = f"src.plugins.{package}"
        if p is not None:
            mod = getattr(p, "module", None)
            module_name = getattr(mod, "__name__", "") or module_name
        meta = stub
        if p is not None and getattr(p, "metadata", None) is not None:
            meta = metadata_to_dict(p.metadata) or stub
        elif stub:
            meta = stub
        role = package_load_role(package)
        visible, ign, hid = _help_flags(nb_name, package)
        rows.append({
            "name": package,
            "nb_plugin_name": nb_name,
            "module": module_name,
            "metadata": meta,
            "load_role": role,
            "loaded_in_process": loaded,
            "has_config": package_has_config_module(package),
            "help_visible": visible,
            "help_ignored": ign,
            "help_hidden": hid,
        })

    from nonebot import get_loaded_plugins

    for p in get_loaded_plugins():
        nb_name = str(getattr(p, "name", "") or "").strip()
        if not nb_name:
            continue
        mod = getattr(p, "module", None)
        module_name = getattr(mod, "__name__", "") if mod is not None else ""
        short = module_name.rsplit(".", 1)[-1] if module_name else ""
        if short in seen_packages:
            continue
        if not is_infrastructure_plugin_name(nb_name, module_name):
            continue
        visible, ign, hid = _help_flags(nb_name, short or nb_name)
        rows.append({
            "name": nb_name,
            "nb_plugin_name": nb_name,
            "module": module_name,
            "metadata": metadata_to_dict(getattr(p, "metadata", None)),
            "load_role": "infra",
            "loaded_in_process": True,
            "has_config": False,
            "help_visible": visible,
            "help_ignored": ign,
            "help_hidden": hid,
        })

    rows.sort(key=lambda x: (x.get("load_role") != "infra", (x.get("metadata") or {}).get("name") or x["name"]))
    return rows


def resolve_catalog_plugin_module(plugin_name: str) -> str | None:
    """按目录名或 NoneBot 插件名解析 ``src.plugins.*`` 模块路径。"""
    target = (plugin_name or "").strip()
    if not target:
        return None
    _, by_package = _loaded_plugin_index()
    p = by_package.get(target)
    if p is not None:
        mod = getattr(p, "module", None)
        return getattr(mod, "__name__", "") if mod is not None else None
    if (_PLUGINS_ROOT / target / "__init__.py").is_file():
        return f"src.plugins.{target}"
    return None


def load_config_class_for_package(package: str) -> type | None:
    module_name = resolve_catalog_plugin_module(package)
    if not module_name:
        return None
    cfg_mod_name = f"{module_name}.config" if not module_name.endswith(".config") else module_name
    try:
        cfg_mod = importlib.import_module(cfg_mod_name)
    except Exception:
        return None
    cfg_cls = getattr(cfg_mod, "Config", None)
    if cfg_cls is None or not isinstance(cfg_cls, type):
        return None
    return cfg_cls
