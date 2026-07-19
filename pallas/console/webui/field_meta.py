"""WebUI 配置字段：从 Pydantic 注解推导 kind / enum choices。"""

from __future__ import annotations

from typing import Any, Literal, get_args, get_origin


def literal_choices(ann: Any) -> list[str] | None:
    if get_origin(ann) is Literal:
        return [str(x) for x in get_args(ann)]
    return None


# 字段名/env_key 命中这些词时，默认按密钥处理（前端打码 + 眼睛切换）。
_SECRET_NAME_HINTS = ("secret", "password", "passwd", "token", "apikey", "api_key", "appkey", "app_key")


def numeric_bounds(field: Any) -> tuple[float | None, float | None]:
    """从 Pydantic v2 字段约束推导 (min, max)。

    ``Field(ge=, le=, gt=, lt=)`` 在 v2 中存于 ``field.metadata``，分别是
    ``annotated_types`` 的 ``Ge/Le/Gt/Lt`` 实例。``gt``/``lt`` 一并按 min/max 取原值，
    前端仅作输入边界提示，不区分开闭区间。
    """
    lo: float | None = None
    hi: float | None = None
    for meta in getattr(field, "metadata", None) or ():
        for attr in ("ge", "gt"):
            val = getattr(meta, attr, None)
            if val is not None:
                lo = float(val) if lo is None else min(lo, float(val))
        for attr in ("le", "lt"):
            val = getattr(meta, attr, None)
            if val is not None:
                hi = float(val) if hi is None else max(hi, float(val))
    return lo, hi


def _extra_dict(field: Any) -> dict[str, Any]:
    extra = getattr(field, "json_schema_extra", None)
    return extra if isinstance(extra, dict) else {}


def is_secret_field(key: str, env_key: str, field: Any) -> bool:
    """显式 ``json_schema_extra={"secret": ...}`` 优先；否则按名称启发式兜底。"""
    extra = _extra_dict(field)
    if "secret" in extra:
        return bool(extra["secret"])
    haystack = f"{key} {env_key}".lower()
    return any(hint in haystack for hint in _SECRET_NAME_HINTS)


def is_multiline_field(field: Any) -> bool:
    return bool(_extra_dict(field).get("multiline"))


def field_kind_from_annotation(ann: Any) -> str:
    if literal_choices(ann) is not None:
        return "enum"
    text = str(ann).lower()
    if "list" in text or "dict" in text or "set" in text or "tuple" in text:
        return "json"
    if "bool" in text:
        return "bool"
    if "int" in text:
        return "int"
    if "float" in text:
        return "float"
    return "string"


def _jsonable_value(v: Any) -> Any:
    from pydantic import BaseModel
    from pydantic_core import PydanticUndefined

    if v is PydanticUndefined:
        return None
    if isinstance(v, BaseModel):
        return v.model_dump(mode="python")
    if isinstance(v, dict):
        return {str(k): _jsonable_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_jsonable_value(x) for x in v]
    if isinstance(v, (set, tuple)):
        return [_jsonable_value(x) for x in v]
    return v


def field_meta_for_model_field(*, key: str, field: Any, env_key: str, cur: Any, default_value: Any) -> dict[str, Any]:
    from pydantic_core import PydanticUndefined

    from pallas.console.webui.field_help import normalize_field_description
    from pallas.console.webui.field_labels import webui_field_label

    ann = field.annotation
    choices = literal_choices(ann)
    default = None if default_value is PydanticUndefined else default_value
    label = webui_field_label(key)
    kind = field_kind_from_annotation(ann)
    extra = _extra_dict(field)
    row: dict[str, Any] = {
        "name": key,
        "kind": kind,
        "required": bool(field.is_required()),
        "description": normalize_field_description(str(field.description or "")),
        "env_key": env_key,
        "default": _jsonable_value(default),
        "current": _jsonable_value(cur),
    }
    extra_label = extra.get("label")
    if isinstance(extra_label, str) and extra_label.strip():
        row["label"] = extra_label.strip()
    elif label:
        row["label"] = label
    if choices is not None:
        row["choices"] = choices
        from pallas.console.webui.enum_labels import attach_choice_labels

        attach_choice_labels(row)
    if kind in ("int", "float"):
        lo, hi = numeric_bounds(field)
        if lo is not None:
            row["min_value"] = lo if kind == "float" else int(lo)
        if hi is not None:
            row["max_value"] = hi if kind == "float" else int(hi)
    if kind == "string":
        if is_secret_field(key, env_key, field):
            row["secret"] = True
        if is_multiline_field(field):
            row["multiline"] = True
    for ui_key in ("ui_group", "ui_order", "ui_hidden"):
        if ui_key in extra:
            row[ui_key] = extra[ui_key]
    return row
