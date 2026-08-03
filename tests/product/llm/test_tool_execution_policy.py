import asyncio

import pytest

from pallas.product.llm.tools import registry
from pallas.product.llm.tools.background import (
    clear_background_tool_state,
    drain_background_tool_events,
    resume_background_tool_tasks,
    start_background_tool,
)
from pallas.product.llm.tools.background_store import create_background_tool_task
from pallas.product.llm.tools.context import ToolInvokeContext
from pallas.product.llm.tools.contracts import ToolCapability


def test_tool_execution_requires_approval_when_declared(monkeypatch) -> None:
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)
    registry.clear_tool_registry()
    registry.register_tool(
        registry.LlmToolSpec(
            name="demo.approved",
            description="approval demo",
            parameters={"type": "object"},
            domains=frozenset({"demo"}),
            handler=lambda _args, _ctx: {"ok": True},
            approval_required=True,
        )
    )

    result = asyncio.run(registry.execute_tool_async("demo.approved", {}))

    assert result["ok"] is False
    assert result["error"] == "approval_required"


@pytest.mark.asyncio
async def test_background_tool_result_is_replayed_only_to_its_original_session(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_background_tool_state()
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)
    registry.clear_tool_registry()
    context = ToolInvokeContext(bot_id=1, group_id=2, user_id=3)

    async def execute(_args, _context) -> dict[str, object]:
        return {"ok": True, "result": {"summary": "done"}}

    registry.register_tool(
        registry.LlmToolSpec(
            name="demo.background",
            description="background demo",
            parameters={"type": "object"},
            domains=frozenset({"demo"}),
            handler=execute,
            background_ok=True,
        )
    )

    queued = start_background_tool(
        tool_name="demo.background",
        arguments={},
        context=context,
        max_execution_ms=1000,
    )
    await asyncio.sleep(0)

    assert queued["status"] == "running"
    assert drain_background_tool_events(ToolInvokeContext(bot_id=1, group_id=2, user_id=4)) == []
    events = drain_background_tool_events(context)
    assert events[0]["tool"] == "demo.background"
    assert events[0]["status"] == "completed"
    assert events[0]["result"] == {"summary": "done"}


@pytest.mark.asyncio
async def test_background_tool_recovery_re_resolves_an_allowlisted_tool(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_background_tool_state()
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)
    registry.clear_tool_registry()
    calls: list[dict[str, object]] = []

    async def handler(args, _context):
        calls.append(args)
        return {"ok": True, "result": {"summary": "recovered"}}

    registry.register_tool(
        registry.LlmToolSpec(
            name="demo.background",
            description="background demo",
            parameters={"type": "object"},
            domains=frozenset({"demo"}),
            handler=handler,
            background_ok=True,
        )
    )
    context = ToolInvokeContext(bot_id=1, group_id=2, user_id=3, approved_tools=frozenset({"demo.background"}))
    create_background_tool_task(
        tool_name="demo.background",
        arguments={"value": "saved"},
        context=context,
        max_execution_ms=1_000,
    )

    assert await resume_background_tool_tasks() == 1
    await asyncio.sleep(0)

    assert calls == [{"value": "saved"}]
    assert drain_background_tool_events(context)[0]["result"] == {"summary": "recovered"}


@pytest.mark.asyncio
async def test_background_recovery_rejects_non_idempotent_side_effects(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_background_tool_state()
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)
    registry.clear_tool_registry()
    called = False

    async def handler(_args, _context):
        nonlocal called
        called = True
        return {"ok": True}

    registry.register_tool(
        registry.LlmToolSpec(
            name="demo.side_effect",
            description="side effect demo",
            parameters={"type": "object"},
            domains=frozenset({"demo"}),
            handler=handler,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
            background_ok=True,
        )
    )
    context = ToolInvokeContext(bot_id=1, group_id=2, user_id=3)
    create_background_tool_task(
        tool_name="demo.side_effect",
        arguments={},
        context=context,
        max_execution_ms=1_000,
    )

    assert await resume_background_tool_tasks() == 0
    assert called is False
    event = drain_background_tool_events(context)[0]
    assert event["status"] == "failed"
    assert event["error"] == "background_recovery_not_idempotent"
