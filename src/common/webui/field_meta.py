"""WebUI 配置字段：从 Pydantic 注解推导 kind / enum choices。"""

from __future__ import annotations

from typing import Any, Literal, get_args, get_origin


def literal_choices(ann: Any) -> list[str] | None:
    if get_origin(ann) is Literal:
        return [str(x) for x in get_args(ann)]
    return None


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

    ann = field.annotation
    choices = literal_choices(ann)
    default = None if default_value is PydanticUndefined else default_value
    row: dict[str, Any] = {
        "name": key,
        "kind": field_kind_from_annotation(ann),
        "required": bool(field.is_required()),
        "description": str(field.description or ""),
        "env_key": env_key,
        "default": _jsonable_value(default),
        "current": _jsonable_value(cur),
    }
    if choices is not None:
        row["choices"] = choices
    return row
