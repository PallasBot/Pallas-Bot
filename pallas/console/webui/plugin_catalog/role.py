"""插件加载角色与分片进程展示判定。"""

from __future__ import annotations


def package_load_role(package: str) -> str:
    from pallas.core.platform.bot_runtime.roles import (
        HUB_PLUGIN_MODULES,
        WORKER_SKIP_PLUGIN_NAMES,
        is_sharding_active,
        is_unified_role,
    )

    if package == "ingress_gate":
        if is_unified_role() or not is_sharding_active():
            return "both"
        return "worker"
    if package == "relogin_forward":
        return "worker"
    if package == "maa_hub":
        return "hub"
    if is_unified_role() or not is_sharding_active():
        return "both"
    if package.startswith("_"):
        return "internal"
    hub_short = {m.rsplit(".", 1)[-1] for m in HUB_PLUGIN_MODULES}
    if package in WORKER_SKIP_PLUGIN_NAMES:
        return "hub"
    if package in hub_short:
        return "hub"
    return "worker"


def resolve_catalog_process_role() -> str:
    """当前响应插件目录的 NoneBot 进程角色。"""
    from pallas.core.platform.bot_runtime.roles import is_sharded_hub, is_sharded_worker, is_unified_role

    if is_unified_role():
        return "unified"
    if is_sharded_hub():
        return "hub"
    if is_sharded_worker():
        return "worker"
    return "unified"


def expected_loaded_in_catalog_process(load_role: str, catalog_role: str) -> bool:
    """该插件是否应在 catalog_process_role 对应进程中加载。"""
    role = (load_role or "").strip()
    if catalog_role == "unified":
        return role in ("both", "infra")
    if catalog_role == "hub":
        return role in ("hub", "infra", "both")
    if catalog_role == "worker":
        return role in ("worker", "internal")
    return True


def should_show_in_plugin_catalog(package: str) -> bool:
    """单进程 unified 下不展示分片专用、本进程未加载的插件。"""
    from pallas.core.platform.bot_runtime.roles import (
        is_unified_role,
        unified_catalog_hidden_plugin_names,
    )

    if is_unified_role() and package in unified_catalog_hidden_plugin_names():
        return False
    return True
