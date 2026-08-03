"""LLM runtime 调试：request snapshot 与 trace 落盘。"""

from __future__ import annotations

import copy
import json
import re
import time
import uuid
from pathlib import Path  # noqa: TC003
from typing import Any

from pallas.core.foundation.paths import plugin_data_dir

_RETIRED_PERSONA_DEBUG_SECTION_RE = re.compile(
    r"(?ms)^【(?:本轮牛格塑形|情境触发|语料收尾参考|收尾变化参考)】.*?(?=^【|\Z)"
)
_RETIRED_PERSONA_DEBUG_SECTION_NAMES = ("本轮牛格塑形", "情境触发", "语料收尾参考", "收尾变化参考")
_RETIRED_PERSONA_DEBUG_FIELDS = ("dynamic_expression", "compare_note", "corpus_ending")


def runtime_debug_dir() -> Path:
    path = plugin_data_dir("pb_webui", create=True) / "llm_runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def request_snapshot_path() -> Path:
    return runtime_debug_dir() / "request_snapshots.jsonl"


def runtime_trace_path() -> Path:
    return runtime_debug_dir() / "runtime_traces.jsonl"


def select_pool_observation_path() -> Path:
    return runtime_debug_dir() / "select_pool_observations.jsonl"


def append_select_pool_observation(
    *,
    bot_id: int,
    group_id: int,
    user_id: int,
    source: str,
    diag: dict[str, Any],
) -> None:
    row = {
        "created_at": int(time.time()),
        "bot_id": int(bot_id),
        "group_id": int(group_id),
        "user_id": int(user_id),
        "source": str(source or ""),
        "diag": diag,
    }
    with select_pool_observation_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _preview_text(text: str, *, limit: int = 160) -> str:
    plain = str(text or "").strip()
    if len(plain) <= limit:
        return plain
    return plain[: limit - 1].rstrip() + "…"


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "").strip().lower() == "user":
            return str(item.get("content") or "").strip()
    return ""


def build_stage_inputs(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    from pallas.product.persona.shaping_observe import build_persona_shaping_summary

    tool_catalog = metadata.get("tool_catalog") if isinstance(metadata.get("tool_catalog"), dict) else {}
    tools = tool_catalog.get("tools") if isinstance(tool_catalog.get("tools"), list) else []
    hybrid_trace = (
        metadata.get("hybrid_retrieval_trace") if isinstance(metadata.get("hybrid_retrieval_trace"), dict) else {}
    )
    last_user_text = _last_user_message(messages)
    base = {
        "message_count": len(messages),
        "last_user_message": _preview_text(last_user_text),
        "system_prompt_preview": _preview_text(system_prompt, limit=220),
    }
    return {
        "plan": {
            **base,
            "agent_stage_plan": list(metadata.get("agent_stage_plan") or []),
        },
        "retrieve": {
            "query_text": _preview_text(last_user_text),
            "sources": list(hybrid_trace.get("sources") or []),
            "memory": hybrid_trace.get("memory") or {},
            "knowledge": hybrid_trace.get("knowledge") or {},
            "relationship": hybrid_trace.get("relationship") or {},
        },
        "tool_loop": {
            "tools_enabled": bool(metadata.get("tools_enabled")),
            "tool_schema_count": int(metadata.get("tool_schema_count") or len(tools)),
            "tool_names": [
                str(
                    item.get("name")
                    or ((item.get("function") or {}).get("name") if isinstance(item.get("function"), dict) else "")
                    or ""
                ).strip()
                for item in tools
                if isinstance(item, dict)
                and str(
                    item.get("name")
                    or ((item.get("function") or {}).get("name") if isinstance(item.get("function"), dict) else "")
                    or ""
                ).strip()
            ][:24],
        },
        "generate": {
            **base,
            "mode": metadata.get("mode"),
            "task": metadata.get("task"),
            "persona_shaping": build_persona_shaping_summary(
                metadata,
                system_prompt=system_prompt,
                task=str(metadata.get("task") or ""),
            ),
        },
    }


def append_request_snapshot(
    *,
    request_id: str,
    task: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> str:
    snapshot_id = f"reqsnap_{uuid.uuid4().hex[:16]}"
    stage_inputs = build_stage_inputs(
        system_prompt=system_prompt,
        messages=messages,
        metadata=metadata,
    )
    row = {
        "request_snapshot_id": snapshot_id,
        "request_id": request_id,
        "created_at": int(time.time()),
        "task": task,
        "system_prompt": system_prompt,
        "messages": messages,
        "agent_stage_plan": list(metadata.get("agent_stage_plan") or []),
        "stage_inputs": stage_inputs,
        "tool_catalog": metadata.get("tool_catalog") or {},
        "persona_shaping": stage_inputs["generate"]["persona_shaping"],
        "metadata_subset": {
            "task": metadata.get("task"),
            "mode": metadata.get("mode"),
            "bot_id": metadata.get("bot_id"),
            "group_id": metadata.get("group_id"),
            "user_id": metadata.get("user_id"),
            "persona_shaping_active": metadata.get("persona_shaping_active"),
        },
    }
    with request_snapshot_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return snapshot_id


def append_runtime_trace(*, request_id: str, trace: dict[str, Any]) -> None:
    row = {
        "request_id": request_id,
        "request_snapshot_id": trace.get("request_snapshot_id"),
        "created_at": int(time.time()),
        "trace": trace,
    }
    with runtime_trace_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _tool_names_from_catalog(tools: list[Any]) -> list[str]:
    names: list[str] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(item.get("name") or fn.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names[:24]


def build_tool_trace_ui(
    *,
    snapshot: dict[str, Any] | None,
    agent_trace: dict[str, Any] | None,
) -> dict[str, Any]:
    """WebUI 工具轨迹摘要：下发 schema + 实际调用轮次。"""
    catalog: dict[str, Any] = {}
    stage_tool: dict[str, Any] = {}
    if isinstance(snapshot, dict):
        raw_catalog = snapshot.get("tool_catalog")
        if isinstance(raw_catalog, dict):
            catalog = raw_catalog
        stage_inputs = snapshot.get("stage_inputs")
        if isinstance(stage_inputs, dict):
            raw_stage = stage_inputs.get("tool_loop")
            if isinstance(raw_stage, dict):
                stage_tool = raw_stage
    tools = catalog.get("tools") if isinstance(catalog.get("tools"), list) else []
    catalog_names = _tool_names_from_catalog(tools)
    trace = agent_trace if isinstance(agent_trace, dict) else {}
    names = [
        str(item).strip()
        for item in list(trace.get("tool_names") or stage_tool.get("tool_names") or catalog_names)
        if str(item).strip()
    ][:24]
    selection = catalog.get("selection") if isinstance(catalog.get("selection"), dict) else {}
    return {
        "tools_enabled": bool(stage_tool.get("tools_enabled") or names or tools),
        "tool_schema_count": int(
            trace.get("tool_schema_count") or stage_tool.get("tool_schema_count") or len(tools) or len(names) or 0
        ),
        "tool_names": names,
        "selection": selection,
        "tool_call_count": int(trace.get("tool_call_count") or 0),
        "status": trace.get("status"),
        "agent_trace": trace or None,
    }


def load_runtime_debug_bundle(*, request_id: str) -> dict[str, Any]:
    snapshot = find_request_snapshot(request_id=request_id)
    trace_row = find_runtime_trace(request_id=request_id)
    persona_shaping: dict[str, Any] | None = None
    if isinstance(snapshot, dict):
        raw = snapshot.get("persona_shaping")
        if isinstance(raw, dict):
            persona_shaping = raw
        else:
            from pallas.product.persona.shaping_observe import build_persona_shaping_summary

            persona_shaping = build_persona_shaping_summary(
                snapshot.get("metadata_subset") if isinstance(snapshot.get("metadata_subset"), dict) else {},
                system_prompt=str(snapshot.get("system_prompt") or ""),
                task=str(snapshot.get("task") or ""),
            )
    trace = (trace_row or {}).get("trace") if isinstance(trace_row, dict) else None
    return {
        "request_id": request_id,
        "snapshot": snapshot,
        "trace": trace,
        "persona_shaping": persona_shaping,
        "tool_trace": build_tool_trace_ui(
            snapshot=snapshot if isinstance(snapshot, dict) else None,
            agent_trace=trace if isinstance(trace, dict) else None,
        ),
    }


def build_runtime_debug_webui_view(bundle: dict[str, Any]) -> dict[str, Any]:
    """Hide retired prompt-shaping details from the console without changing replay input."""
    view = copy.deepcopy(bundle)
    snapshot = view.get("snapshot")
    removed_sections: list[str] = []
    removed_summary_fields: set[str] = set()
    if isinstance(snapshot, dict):
        system_prompt = snapshot.get("system_prompt")
        removed_sections = _retired_persona_debug_sections(system_prompt)
        snapshot["system_prompt"] = _strip_retired_persona_debug_sections(system_prompt)
        removed_summary_fields.update(_sanitize_persona_shaping_summary(snapshot.get("persona_shaping")))
        stage_inputs = snapshot.get("stage_inputs")
        if isinstance(stage_inputs, dict):
            generate = stage_inputs.get("generate")
            if isinstance(generate, dict):
                removed_summary_fields.update(_sanitize_persona_shaping_summary(generate.get("persona_shaping")))
    removed_summary_fields.update(_sanitize_persona_shaping_summary(view.get("persona_shaping")))
    view["debug_view"] = {
        "retired_persona_cleanup": {
            "system_prompt_sections": removed_sections,
            "persona_summary_fields": sorted(removed_summary_fields),
        }
    }
    return view


def _strip_retired_persona_debug_sections(value: object) -> str:
    return _RETIRED_PERSONA_DEBUG_SECTION_RE.sub("", str(value or "")).strip()


def _retired_persona_debug_sections(value: object) -> list[str]:
    plain = str(value or "")
    return [name for name in _RETIRED_PERSONA_DEBUG_SECTION_NAMES if f"【{name}】" in plain]


def _sanitize_persona_shaping_summary(value: object) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    removed: list[str] = []
    for field in _RETIRED_PERSONA_DEBUG_FIELDS:
        if field in value:
            value.pop(field)
            removed.append(field)
    affect_block = str(value.get("affect_block") or "").strip()
    variation_hint = str(value.get("variation_hint") or "").strip()
    if affect_block.startswith("【本轮牛格塑形】"):
        for field in ("affect_block", "lines"):
            if field in value:
                value.pop(field)
                removed.append(field)
        affect_block = ""
    if variation_hint.startswith("【收尾变化参考】"):
        if "variation_hint" in value:
            value.pop("variation_hint")
            removed.append("variation_hint")
        variation_hint = ""
    if "persona_shaping_active" in value:
        value["persona_shaping_active"] = bool(affect_block or variation_hint)
    return tuple(removed)


def build_replay_payload(*, request_id: str, mode: str = "mock_tools") -> dict[str, Any]:
    bundle = load_runtime_debug_bundle(request_id=request_id)
    snapshot = bundle.get("snapshot")
    if not isinstance(snapshot, dict):
        return {"request_id": request_id, "mode": mode, "error": "snapshot_not_found"}
    return {
        "request_id": request_id,
        "request_snapshot_id": snapshot.get("request_snapshot_id"),
        "mode": mode,
        "task": snapshot.get("task"),
        "system_prompt": snapshot.get("system_prompt"),
        "messages": snapshot.get("messages"),
        "agent_stage_plan": snapshot.get("agent_stage_plan"),
        "stage_inputs": snapshot.get("stage_inputs") or {},
        "tool_catalog": snapshot.get("tool_catalog"),
        "metadata_subset": snapshot.get("metadata_subset"),
        "persona_shaping": snapshot.get("persona_shaping"),
        "trace": bundle.get("trace"),
    }


def find_request_snapshot(*, request_id: str) -> dict[str, Any] | None:
    path = request_snapshot_path()
    if not path.is_file():
        return None
    matched: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("request_id") or "") == request_id:
            matched = row
    return matched


def find_runtime_trace(*, request_id: str) -> dict[str, Any] | None:
    path = runtime_trace_path()
    if not path.is_file():
        return None
    matched: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("request_id") or "") == request_id:
            matched = row
    return matched
