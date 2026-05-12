"""在 WebUI 中暴露的「通用配置段」：对应 src/common 下走 .env 的 Pydantic 模型。

新增段：在本文件 `_SECTIONS` 中追加 `WebuiEnvSection` 即可。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import util as importlib_util
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from src.common.env_dotenv import env_value_to_str, upsert_env_dotenv_items


@lru_cache(maxsize=1)
def _message_scrub_models() -> tuple[type[BaseModel], Any]:
    path = Path(__file__).resolve().parent / "message_scrub" / "config.py"
    name = "_pallas_webui_message_scrub_config"
    spec = importlib_util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"message_scrub 配置模块未找到: {path}")
    mod = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MessageScrubConfig, mod.get_message_scrub_config


def _field_kind_from_annotation(ann: Any) -> str:
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


@dataclass(frozen=True)
class WebuiEnvSection:
    id: str
    title: str
    module_label: str
    model_cls: type[BaseModel]
    read_current: Any
    field_to_env: dict[str, str]
    skip_fields: frozenset[str]


def _message_scrub_section() -> WebuiEnvSection:
    msg_cfg_cls, get_msg_cfg = _message_scrub_models()
    field_to_env = {
        "inbound_filter_substrings": "PALLAS_INBOUND_FILTER_SUBSTRINGS",
        "scrub_lexicon_path": "PALLAS_SCRUB_LEXICON_PATH",
        "scrub_lexicon_extra": "PALLAS_SCRUB_LEXICON_EXTRA",
        "scrub_review_providers": "PALLAS_SCRUB_REVIEW_PROVIDERS",
        "scrub_api_url": "PALLAS_SCRUB_API_URL",
        "inbound_filter_api_url": "PALLAS_INBOUND_FILTER_API_URL",
        "inbound_filter_api_key": "PALLAS_INBOUND_FILTER_API_KEY",
        "inbound_filter_api_timeout_sec": "PALLAS_INBOUND_FILTER_API_TIMEOUT_SEC",
        "inbound_filter_api_fail_open": "PALLAS_INBOUND_FILTER_API_FAIL_OPEN",
        "scrub_baidu_api_key": "PALLAS_SCRUB_BAIDU_API_KEY",
        "scrub_baidu_secret_key": "PALLAS_SCRUB_BAIDU_SECRET_KEY",
        "scrub_baidu_censor_url": "PALLAS_SCRUB_BAIDU_CENSOR_URL",
        "scrub_baidu_strategy_id": "PALLAS_SCRUB_BAIDU_STRATEGY_ID",
        "scrub_baidu_block_suspected": "PALLAS_SCRUB_BAIDU_BLOCK_SUSPECTED",
    }
    return WebuiEnvSection(
        id="message_scrub",
        title="消息审查 / 入站过滤",
        module_label="src.common.message_scrub",
        model_cls=msg_cfg_cls,
        read_current=get_msg_cfg,
        field_to_env=field_to_env,
        skip_fields=frozenset({"scrub_review_providers_key_present"}),
    )


_sections_cache: tuple[WebuiEnvSection, ...] | None = None


def _registered_sections() -> tuple[WebuiEnvSection, ...]:
    global _sections_cache
    if _sections_cache is not None:
        return _sections_cache
    parts: list[WebuiEnvSection] = []
    if (Path(__file__).resolve().parent / "message_scrub" / "config.py").is_file():
        parts.append(_message_scrub_section())
    _sections_cache = tuple(parts)
    return _sections_cache


def list_webui_env_sections() -> list[dict[str, str]]:
    return [{"id": s.id, "title": s.title} for s in _registered_sections()]


def get_webui_env_section(section_id: str) -> WebuiEnvSection:
    sid = (section_id or "").strip()
    for s in _registered_sections():
        if s.id == sid:
            return s
    raise ValueError(f"未知 common-config: {section_id}")


def webui_env_section_payload(section_id: str) -> dict[str, Any]:
    s = get_webui_env_section(section_id)
    cfg_obj = s.read_current()
    fields: list[dict[str, Any]] = []
    for key, f in s.model_cls.model_fields.items():
        if key in s.skip_fields:
            continue
        env_key = s.field_to_env.get(key)
        if not env_key:
            continue
        cur = getattr(cfg_obj, key, f.default)
        default_value = None if f.default is PydanticUndefined else f.default
        fields.append({
            "name": key,
            "kind": _field_kind_from_annotation(f.annotation),
            "required": bool(f.is_required()),
            "description": str(f.description or ""),
            "env_key": env_key,
            "default": _jsonable_value(default_value),
            "current": _jsonable_value(cur),
        })
    return {
        "plugin": s.id,
        "module": s.module_label,
        "fields": fields,
    }


def apply_webui_env_section_patch(section_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    s = get_webui_env_section(section_id)
    current = s.read_current().model_dump(mode="python")
    allowed = set(s.field_to_env.keys()) - set(s.skip_fields)
    for k in patch:
        if k not in allowed:
            raise ValueError(f"未知配置项: {k}")
    merged = {**current, **patch}
    validated = s.model_cls(**merged).model_dump(mode="python")
    items = {s.field_to_env[k]: env_value_to_str(validated[k]) for k in patch}
    upsert_env_dotenv_items(items)
    if section_id == "message_scrub":
        try:
            from src.common.message_scrub import reload_message_scrub_caches

            reload_message_scrub_caches()
        except Exception:
            pass
    return webui_env_section_payload(section_id)
