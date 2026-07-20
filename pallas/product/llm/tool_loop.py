"""Bot 内核：本地 tool 多轮补全。"""

from __future__ import annotations

import json
from typing import Any

from nonebot import logger

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.provider_client import complete_chat_message
from pallas.product.llm.tools.context import ToolInvokeContext
from pallas.product.llm.tools.registry import execute_tool_async


def parse_tool_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def tool_result_message(call_id: str, name: str, result: dict[str, Any]) -> dict[str, Any]:
    content = json.dumps({"tool": name, "result": result}, ensure_ascii=False)
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def build_working_messages(
    *,
    system_prompt: str | None,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    working: list[dict[str, Any]] = []
    system = str(system_prompt or "").strip()
    if system:
        working.append({"role": "system", "content": system})
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = item.get("content")
        if not role:
            continue
        working.append({"role": role, "content": content if content is not None else ""})
    return working


def inference_options_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    meta = metadata if isinstance(metadata, dict) else {}
    options: dict[str, Any] = {}
    if meta.get("temperature") is not None:
        try:
            options["temperature"] = float(meta["temperature"])
        except (TypeError, ValueError):
            pass
    if meta.get("token_count") is not None:
        try:
            options["num_predict"] = int(meta["token_count"])
        except (TypeError, ValueError):
            pass
    return options


def resolve_model(metadata: dict[str, Any] | None, *, cfg: LlmConfig) -> str:
    meta = metadata if isinstance(metadata, dict) else {}
    for key in ("resolved_model", "model"):
        raw = str(meta.get(key) or "").strip()
        if raw:
            return raw
    return str(cfg.llm_model or "").strip()


async def complete_with_tool_loop(
    *,
    system_prompt: str | None,
    messages: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    cfg: LlmConfig | None = None,
) -> tuple[str, dict[str, Any]]:
    c = cfg or get_llm_config()
    meta = metadata if isinstance(metadata, dict) else {}
    tool_schemas = meta.get("tool_schemas") if isinstance(meta.get("tool_schemas"), list) else []
    tools_enabled = bool(meta.get("tools_enabled")) and bool(tool_schemas) and bool(c.llm_tools_enabled)
    working = build_working_messages(system_prompt=system_prompt, messages=messages)
    model = resolve_model(meta, cfg=c)
    options = inference_options_from_metadata(meta)
    context = ToolInvokeContext.from_payload(meta)

    if not tools_enabled:
        last_message = await complete_chat_message(working, model=model, options=options, tools=None, cfg=c)
        content = str(last_message.get("content", "") or "").strip()
        assistant_message = dict(last_message)
        assistant_message.setdefault("role", "assistant")
        assistant_message["content"] = content
        return content, assistant_message

    max_rounds = max(1, int(c.llm_tools_max_rounds))
    last_message: dict[str, Any] = {}
    agent_trace: dict[str, Any] = {
        "final_stage": "generate",
        "tool_call_count": 0,
        "rounds": [],
        "status": "success",
    }

    for round_idx in range(max_rounds):
        last_message = await complete_chat_message(
            working,
            model=model,
            options=options,
            tools=tool_schemas,
            cfg=c,
        )
        tool_calls = last_message.get("tool_calls")
        round_trace: dict[str, Any] = {"round": round_idx + 1, "tool_calls": []}
        if not isinstance(tool_calls, list) or not tool_calls:
            content = str(last_message.get("content", "") or "").strip()
            assistant_message = dict(last_message)
            assistant_message.setdefault("role", "assistant")
            assistant_message["content"] = content
            agent_trace["rounds"].append(round_trace)
            assistant_message["_agent_trace"] = agent_trace
            return content, assistant_message

        working.append({
            "role": "assistant",
            "content": last_message.get("content") or "",
            "tool_calls": tool_calls,
        })
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            tool_name = str(fn.get("name") or call.get("name") or "").strip()
            if not tool_name:
                continue
            call_id = str(call.get("id") or tool_name)
            args = parse_tool_arguments(fn.get("arguments"))
            round_trace["tool_calls"].append(tool_name)
            agent_trace["tool_call_count"] = int(agent_trace.get("tool_call_count") or 0) + 1
            logger.info("kernel tool call: round={} tool={} keys={}", round_idx + 1, tool_name, sorted(args.keys()))
            tool_result = await execute_tool_async(tool_name, args, context=context)
            working.append(tool_result_message(call_id, tool_name, tool_result))
        agent_trace["rounds"].append(round_trace)

    content = str(last_message.get("content", "") or "").strip()
    if not content:
        content = "抱歉，工具调用次数已达上限，请换个说法再试。"
    agent_trace["status"] = "max_rounds"
    assistant_message = dict(last_message)
    assistant_message.setdefault("role", "assistant")
    assistant_message["content"] = content
    assistant_message["_agent_trace"] = agent_trace
    return content, assistant_message
