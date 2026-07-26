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


def assistant_history_message(message: dict[str, Any]) -> dict[str, Any]:
    """把 provider 助手消息压成下一轮 messages；保留 reasoning_content 供 thinking 模式回传。"""
    out: dict[str, Any] = {
        "role": "assistant",
        "content": message.get("content") or "",
    }
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        out["tool_calls"] = tool_calls
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        out["reasoning_content"] = reasoning
    return out


def tool_names_from_schemas(schemas: list[Any]) -> list[str]:
    names: list[str] = []
    for item in schemas:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(fn.get("name") or item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names[:24]


def _activate_names_from_tool_result(tool_name: str, result: dict[str, Any]) -> list[str]:
    from pallas.product.llm.tools.discovery import TOOLS_FIND_NAME
    from pallas.product.llm.tools.registry import from_provider_tool_name

    resolved = from_provider_tool_name(tool_name)
    if resolved != TOOLS_FIND_NAME:
        return []
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    if not isinstance(payload, dict):
        return []
    raw = payload.get("activate")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        name = str(item or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _merge_activated_tool_schemas(
    schemas: list[Any],
    activated: list[str],
) -> list[Any]:
    from pallas.product.llm.tools.contracts import ToolCatalogSelection, ToolCatalogSnapshot
    from pallas.product.llm.tools.registry import (
        catalog_entry_for_spec,
        list_registered_tools,
        openai_schemas_from_catalog,
        to_provider_tool_name,
    )

    if not activated:
        return schemas
    existing = {to_provider_tool_name(name) for name in tool_names_from_schemas(schemas)}
    existing.update(tool_names_from_schemas(schemas))
    wanted = {str(name).strip() for name in activated if str(name).strip()}
    specs = [spec for spec in list_registered_tools() if spec.name in wanted]
    if not specs:
        return schemas
    extra = openai_schemas_from_catalog(
        ToolCatalogSnapshot(
            tools=[catalog_entry_for_spec(spec) for spec in specs],
            selection=ToolCatalogSelection(tools_enabled=True, schema_count=len(specs)),
        )
    )
    merged = list(schemas)
    for item in extra:
        fn = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(fn.get("name") or "").strip()
        if name and name not in existing:
            merged.append(item)
            existing.add(name)
    return merged


def summarize_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
    error = str(result.get("error") or "").strip() if isinstance(result, dict) else ""
    payload = result.get("result") if isinstance(result, dict) else result
    preview = ""
    if isinstance(payload, dict):
        summary = str(payload.get("summary") or "").strip()
        command_text = str(payload.get("command_text") or "").strip()
        if summary:
            preview = summary
        elif command_text:
            preview = f"已执行「{command_text}」"
        else:
            preview = json.dumps(payload, ensure_ascii=False)
    elif payload is None:
        preview = ""
    else:
        preview = str(payload)
    if len(preview) > 160:
        preview = preview[:159].rstrip() + "…"
    return {
        "ok": ok,
        "error": error or None,
        "result_preview": preview or None,
    }


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
    effort = str(meta.get("model_effort") or "").strip().lower()
    if effort:
        options["model_effort"] = effort
    return options


def resolve_model(metadata: dict[str, Any] | None, *, cfg: LlmConfig) -> str:
    meta = metadata if isinstance(metadata, dict) else {}
    for key in ("resolved_model", "model"):
        raw = str(meta.get(key) or "").strip()
        if raw:
            return raw
    from pallas.product.llm.providers_store import resolve_endpoint_for_task

    task = str(meta.get("task") or "llm_chat").strip() or "llm_chat"
    endpoint = resolve_endpoint_for_task(task)
    if endpoint is not None and endpoint.model:
        return endpoint.model
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
    task = str(meta.get("task") or "llm_chat").strip() or "llm_chat"
    from pallas.product.llm.vision_messages import prepare_kernel_chat_messages

    user_text = ""
    if working:
        last = working[-1]
        content = last.get("content")
        if isinstance(content, str):
            user_text = content
        elif isinstance(meta.get("vision_plain_text"), str):
            user_text = str(meta.get("vision_plain_text") or "")
    working, provider_row = await prepare_kernel_chat_messages(
        working,
        metadata=meta,
        task=task,
        user_text=user_text,
    )
    if isinstance(metadata, dict):
        metadata["vision_prepared"] = True
        if provider_row is not None:
            from pallas.product.llm.providers_store import provider_capabilities, provider_model_effort

            metadata.setdefault("provider_capabilities", provider_capabilities(provider_row))
            effort = provider_model_effort(provider_row)
            if effort:
                metadata.setdefault("model_effort", effort)

    model = resolve_model(meta, cfg=c)
    options = inference_options_from_metadata(meta)
    if provider_row is not None:
        from pallas.product.llm.providers_store import provider_model_effort, provider_request_method

        effort = provider_model_effort(provider_row)
        if effort and "model_effort" not in options:
            options["model_effort"] = effort
        method = provider_request_method(provider_row)
        if method:
            options["request_method"] = method
    context = ToolInvokeContext.from_payload(meta)

    if not tools_enabled:
        last_message = await complete_chat_message(
            working,
            model=model,
            options=options,
            tools=None,
            cfg=c,
            task=task,
        )
        content = str(last_message.get("content", "") or "").strip()
        assistant_message = dict(last_message)
        assistant_message.setdefault("role", "assistant")
        assistant_message["content"] = content
        return content, assistant_message

    from pallas.product.llm.task_metrics import record_bot_llm_task

    max_rounds = max(1, int(c.llm_tools_max_rounds))
    last_message: dict[str, Any] = {}
    schema_names = tool_names_from_schemas(tool_schemas)
    prefer_required = str(meta.get("tool_choice_prefer") or "").strip().lower() == "required"
    # 口令类工具：提醒模型不要只口头答应
    if schema_names and working and str(working[0].get("role") or "") == "system":
        hint = (
            "【动作工具】用户明确要求执行可用工具对应的动作时，必须先调用对应 function，不要只口头答应或假装已执行。"
            "工具成功后：优先极短自然 ack（如「来了」「房开了」），也可不说话（PASS/空）；"
            "禁止「已派发指令/帮你找找/正在生成」等模板，禁止编造结果；"
            "有明确歌名或玩法口令时可点到，勿把「随机」「随便」当歌名念。"
            "查询类工具用返回结果作答。"
        )
        sys_content = str(working[0].get("content") or "")
        if "【动作工具】" not in sys_content:
            working[0] = {**working[0], "content": f"{sys_content.rstrip()}\n\n{hint}".strip()}
    agent_trace: dict[str, Any] = {
        "final_stage": "generate",
        "tool_call_count": 0,
        "rounds": [],
        "status": "success",
        "tool_loop_enabled": True,
        "tool_schema_count": len(tool_schemas),
        "tool_names": schema_names,
    }

    for round_idx in range(max_rounds):
        round_options = dict(options)
        if prefer_required and round_idx == 0:
            round_options["tool_choice"] = "required"
            # DeepSeek thinking 模式不支持 tool_choice=required
            round_options["model_effort"] = "disable"
        last_message = await complete_chat_message(
            working,
            model=model,
            options=round_options,
            tools=tool_schemas,
            cfg=c,
            task=task,
        )
        tool_calls = last_message.get("tool_calls")
        round_trace: dict[str, Any] = {"round": round_idx + 1, "tool_calls": [], "calls": []}
        if not isinstance(tool_calls, list) or not tool_calls:
            content = str(last_message.get("content", "") or "").strip()
            assistant_message = dict(last_message)
            assistant_message.setdefault("role", "assistant")
            assistant_message["content"] = content
            agent_trace["rounds"].append(round_trace)
            assistant_message["_agent_trace"] = agent_trace
            if int(agent_trace.get("tool_call_count") or 0) <= 0:
                record_bot_llm_task(task, "tool_session_no_call")
            else:
                record_bot_llm_task(task, "tool_session_called")
            return content, assistant_message

        working.append(assistant_history_message(last_message))
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            tool_name = str(fn.get("name") or call.get("name") or "").strip()
            if not tool_name:
                continue
            from pallas.product.llm.tools.registry import from_provider_tool_name

            resolved_name = from_provider_tool_name(tool_name)
            call_id = str(call.get("id") or tool_name)
            args = parse_tool_arguments(fn.get("arguments"))
            round_trace["tool_calls"].append(resolved_name)
            agent_trace["tool_call_count"] = int(agent_trace.get("tool_call_count") or 0) + 1
            logger.info(
                "kernel tool call: round={} tool={} provider_name={} keys={}",
                round_idx + 1,
                resolved_name,
                tool_name,
                sorted(args.keys()),
            )
            tool_result = await execute_tool_async(resolved_name, args, context=context)
            result_dict = tool_result if isinstance(tool_result, dict) else {"ok": True, "result": tool_result}
            summary = summarize_tool_result(result_dict)
            round_trace["calls"].append({
                "tool": resolved_name,
                "provider_name": tool_name,
                "args_keys": sorted(args.keys()),
                "ok": summary["ok"],
                "error": summary["error"],
                "result_preview": summary["result_preview"],
            })
            if summary["ok"]:
                record_bot_llm_task(task, "tool_call_ok")
            else:
                record_bot_llm_task(task, "tool_call_fail")
            working.append(tool_result_message(call_id, resolved_name, tool_result))
            activated = _activate_names_from_tool_result(resolved_name, result_dict)
            if activated:
                tool_schemas = _merge_activated_tool_schemas(tool_schemas, activated)
                schema_names = tool_names_from_schemas(tool_schemas)
                agent_trace["tool_schema_count"] = len(tool_schemas)
                agent_trace["tool_names"] = schema_names
                agent_trace.setdefault("activated_tools", [])
                for name in activated:
                    if name not in agent_trace["activated_tools"]:
                        agent_trace["activated_tools"].append(name)
        agent_trace["rounds"].append(round_trace)

    content = str(last_message.get("content", "") or "").strip()
    if not content:
        content = "抱歉，工具调用次数已达上限，请换个说法再试。"
    agent_trace["status"] = "max_rounds"
    assistant_message = dict(last_message)
    assistant_message.setdefault("role", "assistant")
    assistant_message["content"] = content
    assistant_message["_agent_trace"] = agent_trace
    if int(agent_trace.get("tool_call_count") or 0) > 0:
        record_bot_llm_task(task, "tool_session_called")
    else:
        record_bot_llm_task(task, "tool_session_no_call")
    return content, assistant_message
