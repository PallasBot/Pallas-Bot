"""LLM runtime 调试：request snapshot 与 trace 落盘。"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path  # noqa: TC003
from typing import Any

from pallas.core.foundation.paths import plugin_data_dir


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
    return {
        "request_id": request_id,
        "snapshot": snapshot,
        "trace": (trace_row or {}).get("trace"),
        "persona_shaping": persona_shaping,
    }


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
