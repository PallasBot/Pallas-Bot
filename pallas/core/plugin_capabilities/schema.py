"""按插件聚合命令权限、冷却、LLM tools 与 plugin_storage 声明。"""

from __future__ import annotations

from operator import itemgetter
from typing import Any

from nonebot import logger

from pallas.core.limits.config import get_command_limits_config, normalize_command_limit_overrides
from pallas.core.limits.schema import build_command_limits_ui
from pallas.core.perm.config import get_cmd_perm_config
from pallas.core.perm.schema import build_command_perm_ui
from pallas.core.platform.bot_runtime.plugin_matrix import activation_policy_for_plugin
from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package
from pallas.core.plugin_reload import reload_policy_from_metadata
from pallas.core.storage.schema import build_plugin_storage_ui
from pallas.product.llm.knowledge.metadata import iter_loaded_plugin_knowledge_sources
from pallas.product.llm.tools.metadata import iter_loaded_plugin_llm_tools


def build_plugin_capabilities_ui() -> dict[str, Any]:
    perm_cfg = get_cmd_perm_config()
    limits_cfg = get_command_limits_config()
    perm_ui = build_command_perm_ui(
        {str(k): str(v) for k, v in (perm_cfg.command_permission_overrides or {}).items()},
    )
    limits_ui = build_command_limits_ui(
        normalize_command_limit_overrides(limits_cfg.command_limit_overrides or {}),
    )
    storage_ui = build_plugin_storage_ui()

    plugins: dict[str, dict[str, Any]] = {}

    def ensure_plugin(plugin: str, title: str) -> dict[str, Any]:
        key = canonical_plugin_package((plugin or "").strip()) or (plugin or "").strip()
        if not key:
            key = (plugin or "").strip()
        bucket = plugins.get(key)
        if bucket is None:
            bucket = {
                "plugin": key,
                "title": title or key,
                "commands": {},
                "llm_tools": [],
                "knowledge_sources": [],
                "storage_keys": [],
                "reload_policy": None,
                "activation_policy": None,
            }
            plugins[key] = bucket
        elif title and bucket["title"] == bucket["plugin"]:
            bucket["title"] = title
        return bucket

    for row in perm_ui.get("plugins", []):
        bucket = ensure_plugin(str(row.get("plugin") or ""), str(row.get("title") or ""))
        for cmd in row.get("commands", []):
            cid = str(cmd.get("command_id") or "")
            if not cid:
                continue
            bucket["commands"][cid] = {
                "command_id": cid,
                "label": cmd.get("label") or cid,
                "default_level": cmd.get("default_level"),
                "effective_level": cmd.get("effective_level"),
            }

    for row in limits_ui.get("plugins", []):
        bucket = ensure_plugin(str(row.get("plugin") or ""), str(row.get("title") or ""))
        for cmd in row.get("commands", []):
            cid = str(cmd.get("command_id") or "")
            if not cid:
                continue
            entry = bucket["commands"].setdefault(
                cid,
                {"command_id": cid, "label": cmd.get("label") or cid},
            )
            entry["default_cd_sec"] = cmd.get("default_cd_sec")
            entry["effective_cd_sec"] = cmd.get("effective_cd_sec")
            if not entry.get("label"):
                entry["label"] = cmd.get("label") or cid

    for plugin_name, title, decl in iter_loaded_plugin_llm_tools():
        bucket = ensure_plugin(plugin_name, title)
        bucket["llm_tools"].append({
            "name": decl.name,
            "command_id": decl.command_id,
            "description": decl.description,
        })

    for plugin_name, title, decl in iter_loaded_plugin_knowledge_sources():
        bucket = ensure_plugin(plugin_name, title)
        bucket["knowledge_sources"].append({
            "source_id": decl.source_id,
            "title": decl.title,
            "description": decl.description,
            "retrieval_mode": decl.retrieval_mode.value,
            "scope": decl.scope.value,
        })

    for row in storage_ui.get("plugins", []):
        bucket = ensure_plugin(str(row.get("plugin") or ""), str(row.get("title") or ""))
        bucket["storage_keys"] = list(row.get("keys") or [])

    try:
        from nonebot import get_loaded_plugins

        for plugin in get_loaded_plugins():
            raw_name = str(getattr(plugin, "name", "") or "").strip()
            if not raw_name:
                continue
            name = canonical_plugin_package(raw_name) or raw_name
            meta = getattr(plugin, "metadata", None)
            title = str(getattr(meta, "name", "") or name).strip() if meta else name
            bucket = ensure_plugin(name, title)
            bucket["reload_policy"] = reload_policy_from_metadata(meta)
            bucket["activation_policy"] = activation_policy_for_plugin(name)
            extra = getattr(meta, "extra", None) or {}
            menu_items = extra.get("menu_data") if isinstance(extra, dict) else []
            if isinstance(menu_items, list) and menu_items and bucket["commands"]:
                from pallas.core.perm.menu_display import enrich_commands_with_menu_triggers

                enriched = enrich_commands_with_menu_triggers(
                    list(bucket["commands"].values()),
                    menu_items,
                )
                bucket["commands"] = {str(row["command_id"]): row for row in enriched if row.get("command_id")}
    except ImportError:
        pass
    except Exception:
        logger.exception("build_plugin_capabilities_ui: 读取已加载插件 reload_policy 失败")

    rows_out: list[dict[str, Any]] = []
    for bucket in plugins.values():
        commands = list(bucket["commands"].values())
        commands.sort(key=itemgetter("label", "command_id"))
        llm_tools = list(bucket["llm_tools"])
        llm_tools.sort(key=itemgetter("name"))
        knowledge_sources = list(bucket["knowledge_sources"])
        knowledge_sources.sort(key=itemgetter("source_id"))
        storage_keys = list(bucket["storage_keys"])
        storage_keys.sort(key=itemgetter("key"))
        rows_out.append({
            "plugin": bucket["plugin"],
            "title": bucket["title"],
            "commands": commands,
            "llm_tools": llm_tools,
            "knowledge_sources": knowledge_sources,
            "storage_keys": storage_keys,
            "reload_policy": bucket.get("reload_policy"),
            "activation_policy": bucket.get("activation_policy"),
        })
    rows_out.sort(key=itemgetter("plugin"))
    return {"plugins": rows_out, "levels": perm_ui.get("levels", [])}
