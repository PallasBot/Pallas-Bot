"""WebUI「按插件名」配置读写。"""

from __future__ import annotations

import importlib
from typing import Any

from nonebot import get_loaded_plugins, get_plugin_config, logger
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticUndefined

from pallas.core.foundation.config.repo_settings import env_value_to_str, upsert_repo_settings_items
from pallas.core.platform.plugin_runtime.plugin_identity import canonical_plugin_id
from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule

from .registry import read_plugin_config, reload_plugin_config

_REPEATER_FIELD_TO_ENV = {
    "learn_concurrency": "PALLAS_REPEATER_LEARN_CONCURRENCY",
    "learn_queue_max_size": "PALLAS_REPEATER_LEARN_QUEUE_SIZE",
    "fanout_enabled": "PALLAS_REPEATER_FANOUT_ENABLED",
    "fanout_max_bots": "PALLAS_REPEATER_FANOUT_MAX_BOTS",
}

_PB_STATS_FIELD_TO_ENV = {
    "enabled": "PALLAS_COMMUNITY_STATS_ENABLED",
    "endpoint": "PALLAS_COMMUNITY_STATS_ENDPOINT",
    "token": "PALLAS_COMMUNITY_STATS_TOKEN",
    "interval_sec": "PALLAS_COMMUNITY_STATS_INTERVAL_SEC",
    "roster_public_qq": "PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_QQ",
    "roster_public_profile": "PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_PROFILE",
    "corpus_hot_snapshot_interval_sec": "PALLAS_COMMUNITY_STATS_CORPUS_HOT_SNAPSHOT_INTERVAL_SEC",
}


def plugin_field_env_key(plugin_name: str, field_name: str) -> str:
    canonical = canonical_plugin_id((plugin_name or "").strip())
    if canonical == "repeater":
        return _REPEATER_FIELD_TO_ENV.get(field_name, field_name.upper())
    if canonical == "pb_stats":
        return _PB_STATS_FIELD_TO_ENV.get(field_name, field_name.upper())
    # 点路径（嵌套叶，如 ``skland.github_proxy_url``）→ NoneBot 官方 ``__`` 分隔键。
    if "." in field_name:
        return field_name.replace(".", "__").upper()
    return field_name.upper()


def _is_nested_model_field(field: Any) -> bool:
    ann = getattr(field, "annotation", None)
    return isinstance(ann, type) and issubclass(ann, BaseModel)


def plugin_nested_field_leaves(
    model_cls: type[BaseModel],
    *,
    prefix: str = "",
) -> list[dict[str, Any]]:
    """递归展开嵌套 BaseModel 字段为叶字段列表。

    每个元素含 ``name``（点路径）、``env_key``（``__`` 分隔前缀）、``field``。
    仅展开注解直接是 BaseModel 子类的字段；list/dict 等容器不展开（维持 json 编辑）。
    """
    leaves: list[dict[str, Any]] = []
    for key, f in model_cls.model_fields.items():
        name = f"{prefix}.{key}" if prefix else key
        if _is_nested_model_field(f):
            leaves.extend(plugin_nested_field_leaves(f.annotation, prefix=name))
            continue
        leaves.append({
            "name": name,
            "env_key": name.replace(".", "__").upper(),
            "field": f,
        })
    return leaves


def plugin_config_field_groups(plugin_name: str, fields: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    canonical = canonical_plugin_id((plugin_name or "").strip())
    if canonical != "pb_stats":
        return None
    visible = [f["name"] for f in fields if not f.get("ui_hidden")]
    return [
        {
            "id": "reporting",
            "title": "在线统计",
            "field_names": [name for name in ("enabled", "interval_sec") if name in visible],
        },
        {
            "id": "advanced",
            "title": "自建中心（一般无需改）",
            "field_names": [name for name in ("endpoint", "token") if name in visible],
        },
        {
            "id": "roster",
            "title": "社区主站展示",
            "field_names": [name for name in ("roster_public_qq", "roster_public_profile") if name in visible],
        },
    ]


def schedule_repeater_learn_reload() -> None:
    try:
        import asyncio

        from packages.repeater.learn_queue import reload_repeater_learn_worker_runtime

        loop = asyncio.get_running_loop()
        loop.create_task(reload_repeater_learn_worker_runtime())
    except (RuntimeError, Exception):
        pass


def find_loaded_plugin(plugin_name: str):
    target = canonical_plugin_id((plugin_name or "").strip())
    for p in get_loaded_plugins():
        nb = str(getattr(p, "name", "") or "").strip()
        if canonical_plugin_id(nb) == target:
            return p
        module_name = plugin_module_name(p)
        if module_name and canonical_plugin_id(module_name) == target:
            return p
        short = module_name.rsplit(".", 1)[-1]
        if short and canonical_plugin_id(short) == target:
            return p
    return None


def plugin_module_name(p: Any) -> str:
    mod = getattr(p, "module", None)
    module_name = getattr(mod, "__name__", "") if mod is not None else ""
    if not module_name:
        module_name = str(getattr(p, "module_name", "") or "")
    return module_name.strip()


def maybe_migrate_draw_config(cfg_obj: BaseModel) -> BaseModel:
    draw_config = import_plugin_submodule("draw", "config")
    cfg_cls = getattr(draw_config, "Config", None)
    migrate = getattr(draw_config, "migrate_legacy_gateway_config", None)
    if cfg_cls is None or migrate is None or not isinstance(cfg_obj, cfg_cls):
        return cfg_obj
    return migrate(cfg_obj)


def plugin_config_model_by_name(plugin_name: str):
    canonical = canonical_plugin_id((plugin_name or "").strip())
    if canonical == "pb_core":
        from packages.pb_core.config import Config

        return None, "packages.pb_core", Config
    from pallas.console.webui.plugin_catalog import load_config_class_for_package, resolve_catalog_plugin_module

    p = find_loaded_plugin(plugin_name)
    if p is not None:
        module_name = plugin_module_name(p)
        if not module_name:
            raise ValueError(f"插件模块名为空: {plugin_name}")
        cfg_mod_name = module_name if module_name.endswith(".config") else f"{module_name}.config"
        try:
            cfg_mod = importlib.import_module(cfg_mod_name)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"插件缺少 config.py: {plugin_name}") from e
        cfg_cls = getattr(cfg_mod, "Config", None)
        if cfg_cls is None or not isinstance(cfg_cls, type) or not issubclass(cfg_cls, BaseModel):
            raise ValueError(f"插件 config.py 未定义 Config(BaseModel): {plugin_name}")
        return p, module_name, cfg_cls
    module_name = resolve_catalog_plugin_module(plugin_name)
    if not module_name:
        raise ValueError(f"未找到插件: {plugin_name}")
    cfg_cls = load_config_class_for_package(plugin_name)
    if cfg_cls is None:
        raise ValueError(f"插件缺少 config.py: {plugin_name}")
    return None, module_name, cfg_cls


def field_kind_from_annotation(ann: Any) -> str:
    from .field_meta import field_kind_from_annotation as kind_from_ann

    return kind_from_ann(ann)


def jsonable_value(v: Any) -> Any:
    if v is PydanticUndefined:
        return None
    if isinstance(v, BaseModel):
        return v.model_dump(mode="python")
    if isinstance(v, dict):
        return {str(k): jsonable_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [jsonable_value(x) for x in v]
    if isinstance(v, (set, tuple)):
        return [jsonable_value(x) for x in v]
    return v


def read_current_plugin_config(module_name: str, cfg_cls: type[BaseModel]) -> BaseModel:
    def fallback() -> BaseModel:
        from_env = getattr(cfg_cls, "from_env", None)
        if callable(from_env):
            return from_env()
        try:
            return get_plugin_config(cfg_cls)
        except Exception:
            return cfg_cls()

    return read_plugin_config(module_name, cfg_cls, fallback_getter=fallback)


def format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()))
        msg = str(err.get("msg", "") or "")
        parts.append(f"{loc}: {msg}" if loc else msg)
    text = "; ".join(parts) if parts else str(exc)
    return text[:2000]


def coerce_literal_int_value(annotation: Any, value: Any) -> Any:
    """表单常把数字 Literal 选项以字符串提交；Pydantic Literal[int] 不接受 str。"""
    from typing import Literal, get_args, get_origin

    if get_origin(annotation) is not Literal:
        return value
    args = get_args(annotation)
    if not args or not all(isinstance(a, int) and not isinstance(a, bool) for a in args):
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return int(text, 10)
        except ValueError:
            return value
    return value


def normalize_patch_value(field: Any, value: Any) -> Any:
    """WebUI 空 JSON / null 时对齐 Pydantic 默认值，避免保存 400。"""
    if value is not None:
        return coerce_literal_int_value(field.annotation, value)
    factory = getattr(field, "default_factory", None)
    if factory is not None:
        return factory() if callable(factory) else factory
    if field.default is not PydanticUndefined:
        default = field.default
        if default is not None:
            return default() if callable(default) else default
    ann = str(field.annotation).lower()
    if "list" in ann:
        return []
    if "dict" in ann:
        return {}
    return value


def _nested_get(data: Any, name: str, default: Any = None) -> Any:
    """按点路径从 (dict/对象) 取值；路径缺失返回 default。"""
    if data is None:
        return default
    cur = data
    for part in name.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        else:
            cur = getattr(cur, part, default)
    return cur


def _nested_set(data: dict[str, Any], name: str, value: Any) -> None:
    """按点路径把 value 写入嵌套 dict。"""
    parts = name.split(".")
    target = data
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def plugin_config_payload(
    plugin_name: str,
    *,
    current_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """GET 用默认 ``current``；PUT 落盘后应传 ``validated``，避免 ``get_plugin_config`` 仍为旧内存。"""
    if canonical_plugin_id((plugin_name or "").strip()) == "pb_core":
        from packages.pb_core.config import pb_core_webui_payload

        return pb_core_webui_payload(current_values=current_values)
    p, module_name, cfg_cls = plugin_config_model_by_name(plugin_name)
    cfg_obj = read_current_plugin_config(module_name, cfg_cls)
    if plugin_name == "draw":
        cfg_obj = maybe_migrate_draw_config(cfg_obj)
    fields: list[dict[str, Any]] = []
    for leaf in plugin_nested_field_leaves(cfg_cls):
        name = leaf["name"]
        if current_values is not None:
            cur = _nested_get(current_values, name, _nested_get(cfg_obj, name, leaf["field"].default))
        else:
            cur = _nested_get(cfg_obj, name, leaf["field"].default)
        default_value = None if leaf["field"].default is PydanticUndefined else leaf["field"].default
        from .field_meta import field_meta_for_model_field

        row = field_meta_for_model_field(
            key=name,
            field=leaf["field"],
            env_key=plugin_field_env_key(plugin_name, name),
            cur=cur,
            default_value=default_value,
        )
        extra = getattr(leaf["field"], "json_schema_extra", None)
        if isinstance(extra, dict) and extra.get("ui_hidden"):
            row["ui_hidden"] = True
        fields.append(row)
    payload: dict[str, Any] = {
        "plugin": str(getattr(p, "name", "") or plugin_name) if p is not None else plugin_name,
        "module": module_name,
        "fields": fields,
        "unexpected_keys": plugin_unexpected_env_keys(plugin_name, cfg_cls),
        "hot_reload": True,
    }
    groups = plugin_config_field_groups(plugin_name, fields)
    if groups:
        payload["field_groups"] = groups
    return payload


def plugin_config_env_keys(plugin_name: str, cfg_cls: type[BaseModel]) -> set[str]:
    return {plugin_field_env_key(plugin_name, leaf["name"]) for leaf in plugin_nested_field_leaves(cfg_cls)}


def plugin_unexpected_env_keys(plugin_name: str, cfg_cls: type[BaseModel]) -> list[dict[str, str]]:
    from pallas.core.foundation.config.repo_settings import _load_webui_json_upper

    allowed = plugin_config_env_keys(plugin_name, cfg_cls)
    prefix = f"{plugin_name.upper().replace('-', '_')}_"
    env = _load_webui_json_upper()
    rows: list[dict[str, str]] = []
    for key, value in sorted(env.items()):
        upper = str(key).upper()
        if upper in allowed:
            continue
        if not (upper.startswith(prefix) or upper in allowed):
            continue
        preview = str(value)
        if len(preview) > 120:
            preview = preview[:119] + "…"
        rows.append({"env_key": upper, "value_preview": preview})
    return rows


def plugin_config_raw_toml(plugin_name: str) -> str:
    import json

    _, _, cfg_cls = plugin_config_model_by_name(plugin_name)
    from pallas.core.foundation.config.repo_settings import _load_webui_json_upper

    env = _load_webui_json_upper()
    lines = [f"# plugin: {plugin_name}", "", "[env]"]
    for leaf in plugin_nested_field_leaves(cfg_cls):
        env_key = plugin_field_env_key(plugin_name, leaf["name"])
        if env_key in env:
            lines.append(f"{env_key} = {json.dumps(str(env[env_key]), ensure_ascii=False)}")
    for row in plugin_unexpected_env_keys(plugin_name, cfg_cls):
        ek = row["env_key"]
        if ek in env:
            lines.append(f"{ek} = {json.dumps(str(env[ek]), ensure_ascii=False)}")
    lines.append("")
    return "\n".join(lines)


def apply_plugin_config_raw_toml(plugin_name: str, text: str) -> dict[str, Any]:
    import tomllib

    raw = (text or "").strip()
    if not raw:
        raise ValueError("TOML 内容为空")
    try:
        doc = tomllib.loads(raw.encode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"TOML 解析失败: {exc}") from exc
    env_block = doc.get("env") if isinstance(doc.get("env"), dict) else doc
    if not isinstance(env_block, dict):
        raise ValueError("缺少 [env] 表")
    _, _, cfg_cls = plugin_config_model_by_name(plugin_name)
    reverse = {plugin_field_env_key(plugin_name, leaf["name"]): leaf for leaf in plugin_nested_field_leaves(cfg_cls)}
    patch: dict[str, Any] = {}
    for env_key, value in env_block.items():
        leaf = reverse.get(str(env_key).upper())
        if leaf:
            patch[leaf["name"]] = value
    if not patch:
        raise ValueError("没有可识别的插件配置键")
    return apply_plugin_config_patch(plugin_name, patch)


def apply_plugin_config_patch(
    plugin_name: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    if canonical_plugin_id((plugin_name or "").strip()) == "pb_core":
        from packages.pb_core.config import apply_pb_core_patch

        return apply_pb_core_patch(patch)
    _, module_name, cfg_cls = plugin_config_model_by_name(plugin_name)
    current = read_current_plugin_config(module_name, cfg_cls).model_dump(mode="python")
    leaves = plugin_nested_field_leaves(cfg_cls)
    allowed = {leaf["name"]: leaf["field"] for leaf in leaves}
    normalized: dict[str, Any] = {}
    nested_patch: dict[str, Any] = {}
    for k, v in patch.items():
        field = allowed.get(k)
        if field is None:
            raise ValueError(
                f"未知配置项: {k}（请确认 Bot 已更新并重启；WebUI 无需单独加字段表）",
            )
        normalized[k] = normalize_patch_value(field, v)
    # 点路径（嵌套叶）重建嵌套 dict；标量保留原名。
    for k, v in normalized.items():
        if "." in k:
            _nested_set(nested_patch, k, v)
        else:
            nested_patch[k] = v
    merged = {**current, **nested_patch}
    try:
        validated_obj = cfg_cls(**merged)
        if plugin_name == "draw":
            validated_obj = maybe_migrate_draw_config(validated_obj)
        validated = validated_obj.model_dump(mode="python")
    except ValidationError as e:
        raise ValueError(format_validation_error(e)) from e
    env_items = {plugin_field_env_key(plugin_name, k): env_value_to_str(_nested_get(validated, k)) for k in normalized}
    upsert_repo_settings_items(env_items)
    try:
        reload_plugin_config(module_name)
    except Exception as e:
        logger.warning("插件配置保存后重载失败，plugin [{}]：{}", plugin_name, e)
    try:
        from pallas.core.plugin_reload.metadata_index import reload_metadata_after_plugin_config_save

        reload_metadata_after_plugin_config_save(plugin_name)
    except Exception:
        logger.exception("Plugin configuration save could not reload the metadata index for plugin [{}]", plugin_name)
    canonical = canonical_plugin_id((plugin_name or "").strip())
    if canonical == "repeater" and {"learn_concurrency", "learn_queue_max_size"} & normalized.keys():
        schedule_repeater_learn_reload()
    return plugin_config_payload(plugin_name, current_values=validated)
