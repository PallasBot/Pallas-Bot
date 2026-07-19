"""牛牛核心插件 WebUI 配置（原通用配置横切段聚合）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from pallas.console.webui.registry import PluginWebuiConfigHooks, register_plugin_webui_config

# 各段字段归属（用于 PATCH 路由）
_MESSAGE_SCRUB_FIELDS = frozenset({
    "inbound_filter_substrings",
    "scrub_lexicon_path",
    "scrub_lexicon_extra",
    "scrub_review_providers",
    "scrub_api_url",
    "inbound_filter_api_url",
    "inbound_filter_api_key",
    "inbound_filter_api_timeout_sec",
    "inbound_filter_api_fail_open",
    "scrub_baidu_api_key",
    "scrub_baidu_secret_key",
    "scrub_baidu_censor_url",
    "scrub_baidu_strategy_id",
    "scrub_baidu_block_suspected",
})
_MAIL_FIELDS = frozenset({"smtp_user", "smtp_password", "smtp_server", "smtp_port"})
_INGRESS_FANOUT_FIELDS = frozenset({"greeting_fanout_texts"})
_INGRESS_DISPATCH_FIELDS = frozenset({
    "matcher_dispatch_enabled",
    "route_index_enabled",
    "dispatch_lanes_enabled",
    "send_queue_enabled",
})

_PB_CORE_SECTION_ORDER: tuple[tuple[str, frozenset[str]], ...] = (
    ("message_scrub", _MESSAGE_SCRUB_FIELDS),
    ("ingress_fanout", _INGRESS_FANOUT_FIELDS),
    ("ingress_dispatch", _INGRESS_DISPATCH_FIELDS),
    ("mail", _MAIL_FIELDS),
    ("control_plane", frozenset()),  # 动态解析
    ("corpus_federation", frozenset()),
)

_FIELD_TO_SECTION: dict[str, str] = {}
for _sid, _names in _PB_CORE_SECTION_ORDER:
    for _name in _names:
        _FIELD_TO_SECTION[_name] = _sid


class Config(BaseModel):
    """占位模型；实际读写走各子段 payload。"""

    model_config = ConfigDict(extra="allow")


def _load_control_plane_field_names() -> frozenset[str]:
    from pallas.console.webui.control_plane_section import _FIELD_ORDER

    return frozenset(_FIELD_ORDER)


def _load_corpus_field_names() -> frozenset[str]:
    from pallas.console.webui.corpus_federation_section import _WEBUI_FIELD_NAMES

    return frozenset(_WEBUI_FIELD_NAMES)


def _ensure_field_routes() -> None:
    for name in _load_control_plane_field_names():
        _FIELD_TO_SECTION.setdefault(name, "control_plane")
    for name in _load_corpus_field_names():
        _FIELD_TO_SECTION.setdefault(name, "corpus_federation")


_ensure_field_routes()


def field_section_id(field_name: str) -> str | None:
    sid = _FIELD_TO_SECTION.get(field_name)
    if sid:
        return sid
    if field_name in _load_control_plane_field_names():
        return "control_plane"
    if field_name in _load_corpus_field_names():
        return "corpus_federation"
    return None


def _section_payload(section_id: str, *, current_values: dict[str, Any] | None = None) -> dict[str, Any]:
    if section_id == "control_plane":
        from pallas.console.webui.control_plane_section import control_plane_payload

        return control_plane_payload(current_values=current_values)
    if section_id == "corpus_federation":
        from pallas.console.webui.corpus_federation_section import corpus_federation_payload

        return corpus_federation_payload(current_values=current_values)
    from pallas.console.webui.env_sections import webui_env_section_payload

    return webui_env_section_payload(section_id, current_values=current_values)


def _section_visible(section_id: str) -> bool:
    if section_id == "message_scrub":
        try:
            from pallas.product.message_scrub.config import is_message_scrub_enabled

            return is_message_scrub_enabled()
        except Exception:
            return False
    return True


def _merge_current_values(
    base: dict[str, Any] | None,
    section_id: str,
    part: dict[str, Any],
) -> dict[str, Any] | None:
    if base is None:
        return None
    names = {f["name"] for f in part.get("fields") or []}
    subset = {k: v for k, v in base.items() if k in names}
    return subset or None


def pb_core_webui_payload(*, current_values: dict[str, Any] | None = None) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    field_groups: list[dict[str, Any]] = []
    section_titles = {
        "message_scrub": "消息审查",
        "ingress_fanout": "全员同响口令",
        "ingress_dispatch": "消息处理与发送",
        "mail": "邮件发送（SMTP）",
        "control_plane": "多机协同",
        "corpus_federation": "社区共享接话库",
    }

    for section_id, _ in _PB_CORE_SECTION_ORDER:
        if not _section_visible(section_id):
            continue
        preview = _section_payload(section_id)
        part_current = _merge_current_values(current_values, section_id, preview) if current_values else None
        part = _section_payload(section_id, current_values=part_current)
        part_fields = list(part.get("fields") or [])
        fields.extend(part_fields)
        groups = part.get("field_groups")
        if groups:
            field_groups.extend(
                {
                    **group,
                    "id": f"{section_id}__{group.get('id', 'default')}",
                }
                for group in groups
            )
        elif part_fields:
            field_groups.append({
                "id": section_id,
                "title": section_titles.get(section_id, section_id),
                "field_names": [f["name"] for f in part_fields],
            })

    return {
        "plugin": "pb_core",
        "module": "packages.pb_core",
        "fields": fields,
        "field_groups": field_groups,
        "hot_reload": True,
    }


def _split_patch(patch: dict[str, Any]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for key, value in patch.items():
        sid = field_section_id(key)
        if sid is None:
            raise ValueError(f"未知配置项: {key}")
        buckets.setdefault(sid, {})[key] = value
    return buckets


def apply_pb_core_patch(patch: dict[str, Any]) -> dict[str, Any]:
    if not patch:
        raise ValueError("patch 为空")
    buckets = _split_patch(patch)
    merged_values: dict[str, Any] = {}
    last_payload: dict[str, Any] | None = None
    for section_id, subpatch in buckets.items():
        if section_id == "control_plane":
            from pallas.console.webui.control_plane_section import apply_control_plane_patch

            last_payload = apply_control_plane_patch(subpatch)
        elif section_id == "corpus_federation":
            from pallas.console.webui.corpus_federation_section import apply_corpus_federation_patch

            last_payload = apply_corpus_federation_patch(subpatch)
        else:
            from pallas.console.webui.env_sections import apply_webui_env_section_patch

            last_payload = apply_webui_env_section_patch(section_id, subpatch)
        for row in last_payload.get("fields") or []:
            merged_values[str(row["name"])] = row.get("current")
    return pb_core_webui_payload(current_values=merged_values)


def get_pb_core_config() -> Config:
    return Config()


def reload_pb_core_config() -> None:
    return None


_hooks = PluginWebuiConfigHooks(
    get=get_pb_core_config,
    reload=reload_pb_core_config,
    clear_cache=lambda: None,
)
for _key in ("packages.pb_core", "packages.pb_core.config", "pb_core"):
    register_plugin_webui_config(_key, _hooks)
