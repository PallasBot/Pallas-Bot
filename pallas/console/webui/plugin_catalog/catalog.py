"""插件目录行构建：磁盘发现、元数据、分片角色与可视合并。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pallas.console.webui import plugin_catalog as _repo
from pallas.core.platform.bot_runtime.plugin_matrix import extra_package_for_plugin
from pallas.core.platform.plugin_runtime.plugin_identity import canonical_plugin_id


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
            resolved = canonical_plugin_id(short)
            if resolved:
                by_package.setdefault(resolved, p)
        if nb:
            by_package.setdefault(nb, p)
            resolved = canonical_plugin_id(nb)
            if resolved:
                by_package.setdefault(resolved, p)
    return by_nb_name, by_package


def community_plugin_row_for_plugin(plugin_id: str) -> dict[str, Any] | None:
    from pallas.console.webui.community_plugin_install import community_plugins_root

    pid = (plugin_id or "").strip()
    if not pid:
        return None
    root = community_plugins_root()
    plugin_dir = root / pid
    if not plugin_dir.is_dir():
        return None
    for rel in (_repo.LOCAL_INDEX_REL, _repo.DEFAULT_INDEX_REL):
        try:
            _source, _meta, plugins = _repo.load_index_from_path(rel)
        except Exception:
            continue
        for entry in plugins:
            if str(entry.get("plugin_id") or "").strip() == pid:
                return entry
    return None


def catalog_plugin_source(
    plugin_id: str,
    source: str,
    *,
    module_name: str = "",
) -> str:
    if source == "local" and _repo.community_plugin_row_for_plugin(plugin_id) is not None:
        return "community"
    if source == "extra" or _repo.is_extra_plugin(plugin_id):
        return "official"
    if _repo.community_plugin_row_for_plugin(plugin_id) is not None:
        return "community"
    if source == "pip":
        return (
            _repo.classify_distribution_source(module_name) or _repo.classify_distribution_source(plugin_id) or source
        )
    return source


def build_plugin_catalog_rows(
    *,
    ignored: set[str] | None = None,
    hidden: set[str] | None = None,
    globally_disabled: set[str] | None = None,
    global_disable_protected: set[str] | None = None,
) -> list[dict[str, Any]]:
    """合并磁盘插件与当前进程已加载插件。"""
    ignored = ignored or set()
    hidden = hidden or set()
    globally_disabled = globally_disabled or set()
    global_disable_protected = global_disable_protected or set()
    _, by_package = _repo._loaded_plugin_index()
    extra_pkgs = _repo.discover_extra_plugin_packages()
    try:
        top_level_distributions = _repo.importlib.metadata.packages_distributions()
    except Exception:  # noqa: BLE001
        top_level_distributions = {}
    rows: list[dict[str, Any]] = []
    seen_packages: set[str] = set()

    def _help_flags(nb_name: str, package: str) -> tuple[bool, bool, bool]:
        ids = {nb_name, package, f"packages.{package}"}
        ign = any(x in ignored for x in ids if x)
        hid = any(x in hidden for x in ids if x)
        visible = not ign and not hid
        return visible, ign, hid

    def _append_row(
        *,
        package: str,
        module_name: str,
        nb_name: str,
        meta: dict[str, Any] | None,
        loaded: bool,
        role: str,
        plugin_source: str,
        plugin_source_dir: str | None,
        has_config: bool,
        plugin_root: Path | None = None,
        loaded_plugin: object | None = None,
    ) -> None:
        resolved_plugin_id = _repo.resolved_plugin_identity(package, module_name or nb_name)
        visible, ign, hid = _help_flags(nb_name, resolved_plugin_id)
        ids = {nb_name, package, resolved_plugin_id, f"packages.{resolved_plugin_id}"}
        g_disabled = any(x in globally_disabled for x in ids if x)
        g_protected = any(x in global_disable_protected for x in ids if x)
        root = plugin_root
        if root is None and loaded_plugin is not None:
            mod = getattr(loaded_plugin, "module", None)
            file_path = getattr(mod, "__file__", "") if mod is not None else ""
            if file_path:
                root = Path(file_path).resolve().parent
        plugin_source = _repo.catalog_plugin_source(
            resolved_plugin_id,
            plugin_source,
            module_name=module_name,
        )
        version = _repo.plugin_version(
            resolved_plugin_id,
            plugin_source,
            package_root=root,
            module_name=module_name,
            top_level_distributions=top_level_distributions,
        )
        visuals = _repo.resolve_catalog_visuals(
            plugin_id=resolved_plugin_id,
            plugin_source=plugin_source,
            plugin_root=root,
        )
        uninstall_info = _repo.plugin_uninstall_info(
            plugin_id=resolved_plugin_id,
            plugin_source=plugin_source,
            plugin_source_dir=plugin_source_dir,
            module_name=module_name,
            top_level_distributions=top_level_distributions,
        )
        deps_missing: list[str] = []
        if plugin_source == "community" and root is not None:
            from pallas.core.platform.bot_runtime.plugin_deps import (
                missing_dependencies,
                parse_plugin_dependencies,
            )

            deps_missing = missing_dependencies(parse_plugin_dependencies(root))
        rows.append({
            "name": resolved_plugin_id,
            "nb_plugin_name": nb_name,
            "module": module_name,
            "resolved_plugin_id": resolved_plugin_id,
            "resolved_module": module_name,
            "metadata": meta,
            "load_role": role,
            "loaded_in_process": loaded,
            "has_config": has_config,
            "configurable": has_config,
            "help_visible": visible,
            "help_ignored": ign,
            "help_hidden": hid,
            "globally_disabled": g_disabled,
            "global_disable_protected": g_protected,
            "plugin_source": plugin_source,
            "plugin_source_dir": plugin_source_dir,
            "plugin_version": version,
            "extra_package": extra_package_for_plugin(resolved_plugin_id),
            "uninstallable": uninstall_info["uninstallable"],
            "uninstall_kind": uninstall_info["uninstall_kind"],
            "uninstall_target": uninstall_info["uninstall_target"],
            "deps_missing": deps_missing,
            "avatar": visuals["avatar"],
            "icon": visuals["icon"],
            "cover": visuals["cover"],
        })

    all_packages = sorted(set(_repo.discover_plugin_packages()) | set(extra_pkgs.keys()))
    for package in all_packages:
        if not _repo.should_show_in_plugin_catalog(package):
            continue
        seen_packages.add(package)
        local_root = extra_pkgs.get(package)
        main_root = _repo._PLUGINS_ROOT / package
        disk_root = local_root if local_root is not None else main_root
        if not (disk_root / "__init__.py").is_file():
            continue
        init_path = disk_root / "__init__.py"
        stub = _repo._parse_plugin_metadata_stub(init_path)
        loaded = package in by_package
        p = by_package.get(package)
        nb_name = str(getattr(p, "name", "") or "") if p is not None else package
        module_name = f"packages.{package}"
        if p is not None:
            mod = getattr(p, "module", None)
            module_name = getattr(mod, "__name__", "") or module_name
        meta = stub
        if p is not None and getattr(p, "metadata", None) is not None:
            meta = _repo.metadata_to_dict(p.metadata) or stub
        elif stub:
            meta = stub
        role = _repo.package_load_role(package)
        plugin_source, plugin_source_dir = _repo.infer_plugin_source(package, p, extra_pkgs=extra_pkgs)
        _append_row(
            package=package,
            module_name=module_name,
            nb_name=nb_name,
            meta=meta,
            loaded=loaded,
            role=role,
            plugin_source=plugin_source,
            plugin_source_dir=plugin_source_dir,
            has_config=_repo.package_has_config_module(package, package_root=disk_root),
            plugin_root=disk_root,
            loaded_plugin=p,
        )

    for module_path in _repo.discover_pyproject_plugin_modules():
        package = _repo._module_short_name(module_path)
        if not package or package in seen_packages:
            continue
        seen_packages.add(package)
        p = by_package.get(package)
        loaded = p is not None
        nb_name = str(getattr(p, "name", "") or "") if p is not None else package
        module_name = module_path
        if p is not None:
            mod = getattr(p, "module", None)
            module_name = getattr(mod, "__name__", "") or module_name
        meta = _repo.metadata_to_dict(getattr(p, "metadata", None)) if p is not None else None
        if meta is None:
            meta = _repo._pip_plugin_metadata_stub(module_path)
        _append_row(
            package=package,
            module_name=module_name,
            nb_name=nb_name,
            meta=meta,
            loaded=loaded,
            role="infra",
            plugin_source="nonebot",
            plugin_source_dir=None,
            has_config=_repo.module_has_config_module(module_name),
            loaded_plugin=p,
        )

    for module_paths in _repo.EXTRA_PACKAGE_MODULES.values():
        for module_path in module_paths:
            package = _repo._module_short_name(module_path)
            resolved_plugin_id = canonical_plugin_id(package)
            if not resolved_plugin_id or resolved_plugin_id in seen_packages:
                continue
            if not _repo.should_show_in_plugin_catalog(resolved_plugin_id):
                continue
            seen_packages.add(resolved_plugin_id)
            p = by_package.get(resolved_plugin_id) or by_package.get(package)
            loaded = p is not None
            nb_name = str(getattr(p, "name", "") or "") if p is not None else resolved_plugin_id
            module_name = module_path
            if p is not None:
                mod = getattr(p, "module", None)
                module_name = getattr(mod, "__name__", "") or module_name
            meta = _repo.metadata_to_dict(getattr(p, "metadata", None)) if p is not None else None
            if meta is None:
                meta = _repo._pip_plugin_metadata_stub(module_path)
            if meta is None:
                continue
            _append_row(
                package=resolved_plugin_id,
                module_name=module_name,
                nb_name=nb_name,
                meta=meta,
                loaded=loaded,
                role=_repo.package_load_role(resolved_plugin_id),
                plugin_source="official",
                plugin_source_dir=None,
                has_config=_repo.module_has_config_module(module_name),
                loaded_plugin=p,
            )

    from nonebot import get_loaded_plugins

    for p in get_loaded_plugins():
        nb_name = str(getattr(p, "name", "") or "").strip()
        if not nb_name:
            continue
        mod = getattr(p, "module", None)
        module_name = getattr(mod, "__name__", "") if mod is not None else ""
        if "." in module_name:
            continue
        short = module_name.rsplit(".", 1)[-1] if module_name else ""
        if short in seen_packages:
            continue
        if not _repo.is_infrastructure_plugin_name(nb_name, module_name):
            continue
        plugin_metadata = getattr(p, "metadata", None)
        if (
            _repo.classify_distribution_source(nb_name) is None
            and _repo.classify_distribution_source(module_name) is None
            and plugin_metadata is None
        ):
            continue
        pkg_key = short or nb_name
        seen_packages.add(pkg_key)
        _append_row(
            package=pkg_key,
            module_name=module_name,
            nb_name=nb_name,
            meta=_repo.metadata_to_dict(getattr(p, "metadata", None)),
            loaded=True,
            role="infra",
            plugin_source=(
                _repo.classify_distribution_source(nb_name)
                or _repo.classify_distribution_source(module_name)
                or "nonebot"
            ),
            plugin_source_dir=None,
            has_config=_repo.module_has_config_module(module_name),
            loaded_plugin=p,
        )

    catalog_role = _repo.resolve_catalog_process_role()
    for row in rows:
        row["catalog_process_role"] = catalog_role
        row["expected_in_catalog_process"] = _repo.expected_loaded_in_catalog_process(
            str(row.get("load_role") or ""),
            catalog_role,
        )

    rows.sort(key=lambda x: (x.get("load_role") != "infra", (x.get("metadata") or {}).get("name") or x["name"]))
    return rows
