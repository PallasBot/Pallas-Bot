"""Shared, synchronous and read-only query interface for Arknights MCP and Bot tools."""

from __future__ import annotations

import json
import re
from typing import Any

from pallas.core.domain.arknights import query as ark_query
from pallas.product.arknights_kb.config import ArknightsKbConfig, get_arknights_kb_config
from pallas.product.arknights_kb.prts_corpus import CorpusNotFoundError, CorpusUnavailableError, parse_pack_ids

MAX_RESULT_BYTES = 64 * 1024


def _object_schema(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
    any_of: list[dict[str, list[str]]] | None = None,
):
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    if any_of:
        schema["anyOf"] = any_of
    return schema


_NAME = {"type": "string", "minLength": 1, "maxLength": 80}
_QUERY = {"type": "string", "minLength": 1, "maxLength": 200}
_FILTER = {"type": "array", "maxItems": 10, "items": {"type": "string", "minLength": 1, "maxLength": 80}}
_LIMIT = {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}

QUERY_TOOLS: dict[str, dict[str, Any]] = {
    "arknights.operator.get": {
        "description": "按干员中文名查询基础信息、档案摘录、技能摘要与入职简介。",
        "parameters": _object_schema({"name": _NAME}, required=["name"]),
        "scope": "arknights:read",
    },
    "arknights.operator.search": {
        "description": "按关键词模糊搜索干员中文名。",
        "parameters": _object_schema({"query": _QUERY, "limit": _LIMIT}, required=["query"]),
        "scope": "arknights:read",
    },
    "arknights.skill.get": {
        "description": "查询指定干员某一技能（1/2/3）的专三描述。",
        "parameters": _object_schema(
            {
                "name": _NAME,
                "skill_index": {"type": "integer", "minimum": 1, "maximum": 3},
            },
            required=["name", "skill_index"],
        ),
        "scope": "arknights:read",
    },
    "arknights.enemy.get": {
        "description": "按敌人中文名查询图鉴基础信息与特性。",
        "parameters": _object_schema({"name": _NAME}, required=["name"]),
        "scope": "arknights:read",
    },
    "arknights.enemy.search": {
        "description": "按关键词模糊搜索敌人中文名。",
        "parameters": _object_schema({"query": _QUERY, "limit": _LIMIT}, required=["query"]),
        "scope": "arknights:read",
    },
    "prts.search": {
        "description": "检索本地 PRTS 语料，返回匹配行、资料标题和来源定位。",
        "parameters": _object_schema(
            {
                "query": _QUERY,
                "limit": _LIMIT,
                "games": {**_FILTER, "items": {"type": "string", "enum": ["arknights", "endfield"]}},
                "resource_types": _FILTER,
                "character_names": _FILTER,
                "activity_names": _FILTER,
                "entity_names": _FILTER,
                "speakers": _FILTER,
            },
            required=["query"],
        ),
        "scope": "prts:read",
    },
    "prts.read": {
        "description": "读取 PRTS 搜索结果对应的原文行和来源定位。",
        "parameters": _object_schema(
            {
                "document_uid": {"type": "string", "minLength": 1, "maxLength": 512},
                "document_id": {"type": "string", "minLength": 1, "maxLength": 512},
                "display_title": {"type": "string", "minLength": 1, "maxLength": 512},
                "source_ref": {"type": "string", "minLength": 1, "maxLength": 512},
                "start_line": {"type": "integer", "minimum": 1, "maximum": 1_000_000, "default": 1},
                "end_line": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
                "max_lines": {"type": "integer", "minimum": 1, "maximum": 200, "default": 80},
                "max_chars": {"type": "integer", "minimum": 1000, "maximum": 20_000, "default": 12_000},
            },
            any_of=[{"required": [key]} for key in ("document_uid", "document_id", "display_title", "source_ref")],
        ),
        "scope": "prts:read",
    },
    "prts.timeline": {
        "description": "检索本地 PRTS 参考资料中的时间线与年表。",
        "parameters": _object_schema(
            {
                "query": _QUERY,
                "entity_names": {**_FILTER, "minItems": 1},
                "limit": _LIMIT,
            },
            any_of=[{"required": ["query"]}, {"required": ["entity_names"]}],
        ),
        "scope": "prts:read",
    },
}

_SEARCH_TOOLS = frozenset({"arknights.operator.search", "arknights.enemy.search"})
_PRTS_FILTERS = ("games", "resource_types", "character_names", "activity_names", "entity_names", "speakers")


def _validate_arguments(name: str, arguments: Any) -> dict[str, Any] | None:
    if type(arguments) is not dict:
        return None
    schema = QUERY_TOOLS[name]["parameters"]
    properties = schema["properties"]
    if any(type(key) is not str or key not in properties for key in arguments):
        return None
    if any(key not in arguments for key in schema.get("required", [])):
        return None
    if schema.get("anyOf") and not any(
        all(key in arguments for key in clause["required"]) for clause in schema["anyOf"]
    ):
        return None

    normalized: dict[str, Any] = {}
    for key, value in arguments.items():
        spec = properties[key]
        kind = spec["type"]
        if kind == "string":
            if type(value) is not str:
                return None
            value = value.strip()
            if not value or len(value) > spec.get("maxLength", 2**31):
                return None
            if spec.get("enum") and value not in spec["enum"]:
                return None
        elif kind == "integer":
            if type(value) is not int or value < spec.get("minimum", value) or value > spec.get("maximum", value):
                return None
        elif kind == "array":
            if type(value) is not list or len(value) > spec.get("maxItems", len(value)):
                return None
            if len(value) < spec.get("minItems", 0):
                return None
            item_spec = spec["items"]
            values = []
            for item in value:
                if type(item) is not str:
                    return None
                item = item.strip()
                if not item or len(item) > item_spec.get("maxLength", 2**31):
                    return None
                if item_spec.get("enum") and item not in item_spec["enum"]:
                    return None
                values.append(item)
            value = values
        normalized[key] = value
    if name == "prts.read" and normalized.get("end_line", normalized.get("start_line", 1)) < normalized.get(
        "start_line", 1
    ):
        return None
    return normalized


def _success(result: dict[str, Any]) -> dict[str, Any]:
    response = {"ok": True, "error": "", "result": result}
    try:
        size = len(json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "query_failed", "result": None}
    return response if size <= MAX_RESULT_BYTES else {"ok": False, "error": "output_limit_exceeded", "result": None}


def _failure(error: str) -> dict[str, Any]:
    return {"ok": False, "error": error, "result": None}


def _coverage(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    rarity = str(payload.get("rarity_filter") or "").strip()
    complete = None if not rarity else rarity.upper() == "ALL"
    return {
        "source": str(payload.get("source") or source),
        "complete": complete,
        "coverage_status": "unknown" if complete is None else "complete" if complete else "partial",
        "rarity_filter": rarity,
    }


def _ark_query(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name.startswith("arknights.operator") or name == "arknights.skill.get":
        payload = ark_query.load_kb_operators_payload()
        if not isinstance(payload, dict) or not isinstance(payload.get("operators"), list):
            raise LookupError
        coverage = _coverage(payload, source="operators")
        if name == "arknights.operator.get":
            op = ark_query.query_operator(args["name"], payload=payload)
            result = {"found": op is not None, "name": args["name"], "coverage": coverage}
            if op is not None:
                result["operator"] = op
            return result
        if name == "arknights.operator.search":
            limit = args.get("limit", 5)
            ops = ark_query.search_operators(args["query"], limit=limit, payload=payload)
            return {"query": args["query"], "count": len(ops), "operators": ops, "coverage": coverage}
        skill_index = args["skill_index"]
        skill = ark_query.query_operator_skill(args["name"], skill_index, payload=payload)
        result = {"found": skill is not None, "name": args["name"], "skill_index": skill_index, "coverage": coverage}
        if skill is not None:
            result["skill"] = skill
        return result

    payload = ark_query.load_enemies_payload()
    if not isinstance(payload, dict) or not isinstance(payload.get("enemies"), list):
        raise LookupError
    coverage = _coverage(payload, source="enemies")
    if name == "arknights.enemy.get":
        enemy = ark_query.query_enemy(args["name"], payload=payload)
        result = {"found": enemy is not None, "name": args["name"], "coverage": coverage}
        if enemy is not None:
            result["enemy"] = enemy
        return result
    enemies = ark_query.search_enemies(args["query"], limit=args.get("limit", 5), payload=payload)
    return {"query": args["query"], "count": len(enemies), "enemies": enemies, "coverage": coverage}


def _prts_query(name: str, args: dict[str, Any], cfg: ArknightsKbConfig) -> dict[str, Any]:
    from pallas.product.arknights_kb.prts_runtime import corpus_store

    store = corpus_store()
    pointer = store.snapshot()
    configured = parse_pack_ids(cfg.prts_corpus_packs, include_endfield=cfg.prts_corpus_include_endfield)
    if name == "prts.timeline":
        requested = ["references"] if "references" in configured else []
    else:
        requested = configured
    status = store.status(
        pointer=pointer,
        pack_ids=requested,
        require_search_index=name != "prts.read",
    )
    if not status.get("installed"):
        raise LookupError
    installed = [str(pack.get("pack_id")) for pack in status.get("packs", []) if isinstance(pack, dict)]
    available = [pack for pack in requested if pack in installed]
    if not available:
        raise LookupError
    coverage = {
        "packs": available,
        "complete": len(available) == len(requested),
        "data_version": status["data_version"],
    }

    if name == "prts.read":
        start_line = args.get("start_line", 1)
        end_line = args.get("end_line")
        max_lines = min(args.get("max_lines", cfg.prts_corpus_read_max_lines), cfg.prts_corpus_read_max_lines)
        max_chars = min(args.get("max_chars", cfg.prts_corpus_read_max_chars), cfg.prts_corpus_read_max_chars)
        try:
            result = store.read(
                document_uid=args.get("document_uid", ""),
                document_id=args.get("document_id", ""),
                display_title=args.get("display_title", ""),
                source_ref=args.get("source_ref", ""),
                start_line=start_line,
                end_line=end_line,
                max_lines=max_lines,
                max_chars=max_chars,
                pack_ids=available,
                pointer=pointer,
            )
        except CorpusNotFoundError:
            return {"found": False, "coverage": coverage}
        return {"found": True, **result, "coverage": coverage}

    query = args.get("query", "")
    if not query and name == "prts.timeline":
        query = args["entity_names"][0]
    limit = min(args.get("limit", cfg.prts_corpus_search_limit), cfg.prts_corpus_search_limit)
    filters = {key: args[key] for key in _PRTS_FILTERS if key in args}
    if name == "prts.timeline":
        raw = store.search(query, pack_ids=available, limit=limit, pointer=pointer)
    else:
        raw = store.search(query, pack_ids=available, limit=limit, pointer=pointer, **filters)
        if not raw.get("count"):
            terms = list(dict.fromkeys(re.findall(r"[\u3400-\u9fff]{2,}|[A-Za-z0-9_-]{2,}", query)))
            relaxed = {key: filters[key] for key in ("games", "resource_types", "activity_names") if key in filters}
            for term in terms:
                if term == query:
                    continue
                fallback = store.search(term, pack_ids=available, limit=limit, pointer=pointer, **relaxed)
                if fallback.get("count"):
                    fallback["query"] = query
                    fallback["matched_query"] = term
                    raw = fallback
                    break
    raw["found"] = bool(raw.get("count"))
    raw["coverage"] = coverage
    return raw


def execute_query(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute one allowlisted local query without LLM, Bot startup, or network access."""
    if type(name) is not str or name not in QUERY_TOOLS:
        return _failure("unknown_tool")
    args = _validate_arguments(name, arguments)
    if args is None:
        return _failure("invalid_arguments")
    try:
        cfg = get_arknights_kb_config()
    except Exception:
        return _failure("query_failed")
    if not cfg.arknights_kb_enabled:
        return _failure("source_disabled")
    if name.startswith("prts.") and not cfg.prts_corpus_enabled:
        return _failure("source_disabled")
    try:
        result = _ark_query(name, args) if name.startswith("arknights.") else _prts_query(name, args, cfg)
    except LookupError:
        return _failure("source_unavailable")
    except CorpusUnavailableError:
        return _failure("source_unavailable")
    except CorpusNotFoundError:
        return _success({"found": False, "coverage": {"source": "prts", "complete": True}})
    except Exception:
        return _failure("query_failed")
    return _success(result)
