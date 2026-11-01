"""tool_loop / kernel 单轮预算：真实 HTTP cap 跨工具续轮、在途副作用与诚实收尾。"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.tool_loop import complete_with_tool_loop
from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, clear_tool_registry, register_tool
from pallas.product.llm.tools.reply import register_reply_tools
from pallas.product.llm.turn_budget import LlmTurnBudget, LlmTurnBudgetExceeded


@pytest.fixture(autouse=True)
def reset_tools() -> None:
    reset_llm_tools_bootstrap_for_tests()
    clear_tool_registry()
    yield
    reset_llm_tools_bootstrap_for_tests()
    clear_tool_registry()


class _OkResponse:
    status_code = 200
    headers = {"content-type": "application/json"}
    content = b""
    text = ""

    def __init__(self, message: dict) -> None:
        self._message = message

    def json(self) -> dict:
        return {"choices": [{"message": self._message}]}


def _patch_http(monkeypatch: pytest.MonkeyPatch, responder) -> list[int]:
    posts: list[int] = []

    class FakeClient:
        async def post(self, *_args, **_kwargs):
            posts.append(len(posts) + 1)
            return _OkResponse(responder(len(posts) - 1))

    async def fake_client():
        return FakeClient()

    monkeypatch.setattr("pallas.product.llm.provider_client.get_llm_shared_httpx_client", fake_client)
    monkeypatch.setattr("pallas.product.llm.availability.llm_calls_enabled", lambda cfg=None: True)
    monkeypatch.setattr("pallas.product.llm.providers_store.find_provider", lambda _pid: None)
    monkeypatch.setattr("pallas.product.llm.provider_client.provider_daily_budget_ok", lambda _pid: True)
    from pallas.product.llm.providers_store import ResolvedLlmEndpoint

    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_candidates_for_task",
        lambda _task: [
            ResolvedLlmEndpoint(provider_id="p1", base_url="https://x/v1", api_key="sk", model="m", api_keys=("sk",))
        ],
    )
    return posts


def _register_echo(calls: list[str], *, on_call=None) -> None:
    async def handler(_args, _ctx=None):
        calls.append("echo")
        if on_call is not None:
            on_call()
        return {"ok": True, "result": {"summary": "echo"}}

    register_tool(
        LlmToolSpec(
            name="demo.echo",
            description="回显",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"demo"}),
            handler=handler,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.READ_ONLY.value}),
        )
    )


def _tool_call(name: str, args: str = "{}", call_id: str = "c1") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


async def _run_loop(
    monkeypatch: pytest.MonkeyPatch,
    budget: LlmTurnBudget,
    responder,
    cfg: LlmConfig,
    *,
    tool_names: tuple[str, ...] = ("demo__echo",),
    exit_gate=None,
    tool_call_started=None,
    metadata_extra: dict | None = None,
):
    metadata = {
        "tools_enabled": True,
        "tool_schemas": [{"type": "function", "function": {"name": name}} for name in tool_names],
        "bot_id": 1,
        "user_id": 2,
        "group_id": 3,
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    kwargs = {}
    if exit_gate is not None:
        kwargs["exit_gate"] = exit_gate
    if tool_call_started is not None:
        kwargs["tool_call_started"] = tool_call_started
    return await complete_with_tool_loop(
        system_prompt="sys",
        messages=[{"role": "user", "content": "做事"}],
        metadata=metadata,
        cfg=cfg,
        turn_budget=budget,
        **kwargs,
    )


def _register_effect(calls: list[str], *, on_call=None) -> None:
    async def handler(_args, _ctx=None):
        calls.append("effect")
        if on_call is not None:
            await on_call()
        return {"ok": True, "result": {"summary": "done"}}

    register_tool(
        LlmToolSpec(
            name="demo.effect",
            description="副作用",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"demo"}),
            handler=handler,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
        )
    )


def _register_fail() -> None:
    async def handler(_args, _ctx=None):
        raise RuntimeError("boom")

    register_tool(
        LlmToolSpec(
            name="demo.fail",
            description="失败工具",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"demo"}),
            handler=handler,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.READ_ONLY.value}),
        )
    )


def _stub_history_repo(monkeypatch: pytest.MonkeyPatch, *, count: int = 8) -> None:
    rows = [
        SimpleNamespace(user_id=index % 2 + 11, sender_name=f"群友{index}", plain_text=f"讨论第{index}条", time=index)
        for index in range(count)
    ]

    class Repo:
        async def find_recent_in_group(self, _group_id, *, limit):
            return rows

    monkeypatch.setattr("pallas.core.foundation.db.make_message_repository", lambda: Repo())
    monkeypatch.setattr("pallas.product.llm.tools.history._recent_summary_cache", {})
    monkeypatch.setattr(
        "pallas.product.llm.tools.history._daily_budget",
        SimpleNamespace(ok=lambda _budget: True, bump=lambda _budget: None),
    )


@pytest.mark.asyncio
async def test_http_cap_stops_next_round_after_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _register_echo(calls)
    posts = _patch_http(
        monkeypatch,
        lambda index: {"role": "assistant", "content": "", "tool_calls": [_tool_call("demo__echo")]},
    )
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=1)

    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        None,
        LlmConfig(llm_tools_enabled=True, llm_model="m"),
    )

    assert posts == [1]
    assert calls == ["echo"]
    trace = assistant["_agent_trace"]
    assert trace["budget_exhausted"] is True
    assert trace["budget_exhaust_reason"] == "http_attempts_exhausted"
    assert content == ""


@pytest.mark.asyncio
async def test_last_allowed_success_still_runs_proposed_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _register_echo(calls)

    def responder(index: int) -> dict:
        if index == 0:
            return {"role": "assistant", "content": "", "tool_calls": [_tool_call("demo__echo")]}
        return {"role": "assistant", "content": "完成"}

    posts = _patch_http(monkeypatch, responder)
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=2)

    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        responder,
        LlmConfig(llm_tools_enabled=True, llm_model="m"),
    )

    assert posts == [1, 2]
    assert calls == ["echo"]
    assert content == "完成"
    assert "budget_exhausted" not in assistant["_agent_trace"]


@pytest.mark.asyncio
async def test_gate_await_expired_skips_tool_start(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _register_effect(calls)
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=6)

    def responder(_index: int) -> dict:
        # provider await 期间耗尽 deadline：门禁后、真正执行前必须再查。
        budget.deadline_monotonic = time.monotonic() - 1
        return {"role": "assistant", "content": "", "tool_calls": [_tool_call("demo__effect")]}

    posts = _patch_http(monkeypatch, responder)
    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        responder,
        LlmConfig(llm_tools_enabled=True, llm_model="m"),
        tool_names=("demo__effect",),
    )

    assert calls == []
    assert posts == [1]
    trace = assistant["_agent_trace"]
    assert trace["budget_exhausted"] is True
    assert trace["budget_completed_tool_calls"] == 0
    assert content == ""


@pytest.mark.asyncio
async def test_inflight_side_effect_completes_then_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=6)

    async def expire_after_await() -> None:
        await asyncio.sleep(0)
        budget.deadline_monotonic = time.monotonic() - 1

    _register_effect(calls, on_call=expire_after_await)
    posts = _patch_http(
        monkeypatch,
        lambda index: {"role": "assistant", "content": "", "tool_calls": [_tool_call("demo__effect")]},
    )

    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        None,
        LlmConfig(llm_tools_enabled=True, llm_model="m"),
        tool_names=("demo__effect",),
    )

    assert calls == ["effect"]
    assert posts == [1]
    trace = assistant["_agent_trace"]
    assert trace["budget_exhausted"] is True
    assert trace["budget_exhaust_reason"] == "deadline_exceeded"
    assert trace["budget_completed_tool_calls"] == 1
    assert trace["successful_side_effect_call_count"] == 1
    assert content == ""


@pytest.mark.asyncio
async def test_chat_reply_not_sent_when_later_action_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    register_reply_tools()
    _register_effect([])
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=6)

    def responder(index: int) -> dict:
        if index == 0:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [_tool_call("chat__reply", '{"text": "好了"}')],
            }
        budget.deadline_monotonic = time.monotonic() - 1
        return {"role": "assistant", "content": "", "tool_calls": [_tool_call("demo__effect")]}

    posts = _patch_http(monkeypatch, responder)
    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        responder,
        LlmConfig(llm_tools_enabled=True, llm_model="m"),
        tool_names=("chat__reply", "demo__effect"),
    )

    assert posts == [1, 2]
    assert content == ""
    trace = assistant["_agent_trace"]
    assert trace["budget_exhausted"] is True
    assert trace["reply_source"] == "budget_truncated"


@pytest.mark.asyncio
async def test_action_failure_blocks_reply_on_budget_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    register_reply_tools()
    _register_fail()
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=1)

    def responder(_index: int) -> dict:
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                _tool_call("chat__reply", '{"text": "好了"}', call_id="c1"),
                _tool_call("demo__fail", call_id="c2"),
            ],
        }

    posts = _patch_http(monkeypatch, responder)
    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        responder,
        LlmConfig(llm_tools_enabled=True, llm_model="m"),
        tool_names=("chat__reply", "demo__fail"),
    )

    assert posts == [1]
    assert content == ""
    assert assistant["_agent_trace"]["reply_source"] == "budget_truncated"


@pytest.mark.asyncio
async def test_chat_reply_finishes_without_extra_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    register_reply_tools()
    posts = _patch_http(
        monkeypatch,
        lambda index: {
            "role": "assistant",
            "content": "",
            "tool_calls": [_tool_call("chat__reply", '{"text": "好了"}')],
        },
    )
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=1)

    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        None,
        LlmConfig(llm_tools_enabled=True, llm_model="m"),
        tool_names=("chat__reply",),
    )

    assert posts == [1]
    assert content == "好了"
    trace = assistant["_agent_trace"]
    assert trace["budget_exhausted"] is True
    assert trace["reply_source"] == "chat.reply"


@pytest.mark.asyncio
@pytest.mark.parametrize("tools_enabled", [False, True])
@pytest.mark.parametrize("firewall_enabled", [False, True])
async def test_kernel_chat_job_stops_at_retired_gate_before_provider(
    monkeypatch: pytest.MonkeyPatch, tools_enabled: bool, firewall_enabled: bool
) -> None:
    from pallas.product.llm import kernel_runner

    calls: list[str] = []
    _register_echo(calls)
    posts = _patch_http(
        monkeypatch,
        lambda _index: {"role": "assistant", "content": "", "tool_calls": [_tool_call("demo__echo")]},
    )
    cfg = LlmConfig(
        llm_tools_enabled=tools_enabled,
        llm_model="m",
        llm_chat_enabled=True,
        llm_persona_output_firewall={"enabled": firewall_enabled},
        llm_chat_turn_max_http_attempts=1,
        llm_chat_turn_timeout_sec=1,
    )
    complete = AsyncMock()
    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", complete)
    delivered = AsyncMock(return_value={"message": "ok"})
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", delivered)
    removed = AsyncMock()
    monkeypatch.setattr(kernel_runner.TaskManager, "remove_task", removed)
    traces: list[dict] = []
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace",
        lambda **kwargs: traces.append(kwargs["trace"]),
    )
    released: list[object] = []
    monkeypatch.setattr(
        kernel_runner,
        "release_llm_execution_slot",
        lambda slot, cfg=None: released.append(slot),
    )
    slot = object()
    request_id = f"retired-{tools_enabled}-{firewall_enabled}"

    await kernel_runner.run_kernel_chat_job(
        request_id,
        system_prompt="sys",
        messages=[{"role": "user", "content": "do work"}],
        metadata={
            "task": "llm_chat",
            "bot_id": 1,
            "group_id": 2,
            "user_id": 3,
            "tools_enabled": tools_enabled,
            "tool_schemas": [{"type": "function", "function": {"name": "demo__echo"}}],
        },
        cfg=cfg,
        execution_slot=slot,
    )

    assert posts == []
    assert calls == []
    complete.assert_not_awaited()
    delivered.assert_not_awaited()
    removed.assert_awaited_once_with(request_id)
    assert traces == [
        {
            "status": "skipped",
            "skip_reason": "legacy_agent_retired",
            "side_effect_started": False,
            "agent_trace": None,
        }
    ]
    assert released == [slot]


@pytest.mark.asyncio
async def test_inline_history_shares_parent_budget_cap_one(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.tools.history import register_history_tools

    register_history_tools()
    _stub_history_repo(monkeypatch)
    cfg = LlmConfig(llm_tools_enabled=True, llm_model="m", llm_tools_history_daily_budget=2000)
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: cfg)
    posts = _patch_http(
        monkeypatch,
        lambda index: {"role": "assistant", "content": "", "tool_calls": [_tool_call("chat__recent_summary")]},
    )
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=1)

    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        None,
        cfg,
        tool_names=("chat__recent_summary",),
    )

    # 父轮第 1 次用掉唯一名额；工具内联第 2 次请求被同一预算拦下，不产生第 2 次 POST。
    assert posts == [1]
    trace = assistant["_agent_trace"]
    assert trace["budget_exhausted"] is True
    assert trace["budget_exhaust_reason"] == "http_attempts_exhausted"
    assert content == ""


@pytest.mark.asyncio
async def test_inline_history_consumes_parent_budget_cap_two(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.tools import history as history_mod
    from pallas.product.llm.tools.history import register_history_tools

    register_history_tools()
    _stub_history_repo(monkeypatch)
    cfg = LlmConfig(llm_tools_enabled=True, llm_model="m", llm_tools_history_daily_budget=2000)
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: cfg)

    def responder(index: int) -> dict:
        if index == 0:
            return {"role": "assistant", "content": "", "tool_calls": [_tool_call("chat__recent_summary")]}
        return {"role": "assistant", "content": "大家在讨论。"}

    posts = _patch_http(monkeypatch, responder)
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=2)

    await _run_loop(monkeypatch, budget, responder, cfg, tool_names=("chat__recent_summary",))

    # 父轮第 1 次 + 工具内联第 2 次共占满 cap；若未共享会继续发起第 3 次。
    assert posts == [1, 2]
    assert history_mod._recent_summary_cache


def test_background_context_excludes_turn_budget(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from pallas.product.llm.tools.background import _context_from_task
    from pallas.product.llm.tools.background_store import create_background_tool_task
    from pallas.product.llm.tools.context import ToolInvokeContext

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    context = ToolInvokeContext(
        bot_id=1,
        group_id=2,
        user_id=3,
        turn_budget=LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=6),
    )
    task = create_background_tool_task(tool_name="demo.effect", arguments={}, context=context, max_execution_ms=0)
    assert "turn_budget" not in task
    assert _context_from_task(task).turn_budget is None


def _register_search(calls: list[str]) -> None:
    async def handler(_args, _ctx=None):
        calls.append("search")
        return {"ok": True, "result": {"count": 1, "items": [{"title": "命中"}]}}

    register_tool(
        LlmToolSpec(
            name="demo.search",
            description="查询",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            domains=frozenset({"demo"}),
            handler=handler,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.READ_ONLY.value}),
        )
    )


@pytest.mark.asyncio
async def test_gate_await_expiry_stops_tool_and_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _register_search(calls)
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=6)
    state = {"provider_done": False}

    def responder(_index: int) -> dict:
        state["provider_done"] = True
        return {"role": "assistant", "content": "", "tool_calls": [_tool_call("demo__search")]}

    async def gate(**_kwargs):
        # 门禁 await 期间 deadline 到期：真正执行前必须再查一次。
        if state["provider_done"] and not _kwargs.get("side_effect_started"):
            budget.deadline_monotonic = time.monotonic() - 1

    posts = _patch_http(monkeypatch, responder)
    started = asyncio.Event()
    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        responder,
        LlmConfig(llm_tools_enabled=True, llm_model="m"),
        tool_names=("demo__search",),
        exit_gate=gate,
        tool_call_started=started,
    )

    assert calls == []
    assert posts == [1]
    assert started.is_set() is False
    trace = assistant["_agent_trace"]
    assert trace["tool_call_count"] == 0
    assert trace["budget_exhausted"] is True
    assert trace["budget_exhaust_reason"] == "deadline_exceeded"
    assert content == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("reply_first", [True, False])
async def test_not_offered_action_blocks_reply(monkeypatch: pytest.MonkeyPatch, reply_first: bool) -> None:
    register_reply_tools()
    _register_effect([])
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=1)
    reply_call = _tool_call("chat__reply", '{"text": "房开好了"}', call_id="c1")
    unoffered = _tool_call("demo__effect", call_id="c2")
    tool_calls = [reply_call, unoffered] if reply_first else [unoffered, reply_call]

    def responder(_index: int) -> dict:
        return {"role": "assistant", "content": "", "tool_calls": tool_calls}

    posts = _patch_http(monkeypatch, responder)
    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        responder,
        LlmConfig(llm_tools_enabled=True, llm_model="m"),
        tool_names=("chat__reply",),
    )

    assert posts == [1]
    assert content == ""
    trace = assistant["_agent_trace"]
    assert trace["reply_source"] == "budget_truncated"
    # 未开放不伪计失败执行数，也不计入已执行工具数：只有真正执行的 chat.reply 计 1。
    assert trace["failed_tool_call_count"] == 0
    assert trace["budget_completed_tool_calls"] == 1


@pytest.mark.asyncio
async def test_max_rounds_failure_with_deadline_stops_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    register_reply_tools()
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=2)

    async def failing_effect(_args, _ctx=None):
        await asyncio.sleep(0)
        budget.deadline_monotonic = time.monotonic() - 1
        raise RuntimeError("action failed")

    register_tool(
        LlmToolSpec(
            name="demo.fail",
            description="失败动作",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"demo"}),
            handler=failing_effect,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
        )
    )

    def responder(index: int) -> dict:
        if index == 0:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [_tool_call("chat__reply", '{"text": "房开好了"}')],
            }
        return {"role": "assistant", "content": "", "tool_calls": [_tool_call("demo__fail", call_id="c2")]}

    posts = _patch_http(monkeypatch, responder)
    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        responder,
        LlmConfig(llm_tools_enabled=True, llm_model="m", llm_tools_max_rounds=2),
        tool_names=("chat__reply", "demo__fail"),
    )

    assert posts == [1, 2]
    assert content == ""
    trace = assistant["_agent_trace"]
    assert trace["budget_exhausted"] is True
    assert trace["reply_source"] == "budget_truncated"


@pytest.mark.asyncio
async def test_background_acceptance_is_not_completion(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from pallas.product.llm.tools import background as bg
    from pallas.product.llm.tools import background_store

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    bg.clear_background_tool_state()
    handler_calls: list[bool] = []

    async def handler(_args, ctx=None):
        handler_calls.append(bool(ctx is not None and ctx.is_tool_approved("demo.bg")))
        return {"ok": True, "result": {"summary": "done"}}

    register_tool(
        LlmToolSpec(
            name="demo.bg",
            description="后台副作用",
            parameters={"type": "object", "properties": {"job_id": {"type": "string"}}},
            domains=frozenset({"demo"}),
            handler=handler,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
            approval_required=True,
            idempotency_key="job_id",
            max_execution_ms=0,
            background_ok=True,
        )
    )
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 60, max_http_attempts=1)

    def responder(_index: int) -> dict:
        return {"role": "assistant", "content": "", "tool_calls": [_tool_call("demo__bg", '{"job_id": "j1"}')]}

    posts = _patch_http(monkeypatch, responder)
    content, assistant = await _run_loop(
        monkeypatch,
        budget,
        responder,
        LlmConfig(llm_tools_enabled=True, llm_model="m"),
        tool_names=("demo__bg",),
        metadata_extra={"background_tool_names": ["demo.bg"], "approved_tools": ["demo.bg"]},
    )

    assert posts == [1]
    assert content == ""
    trace = assistant["_agent_trace"]
    assert trace["reply_source"] == "budget_truncated"
    assert trace["successful_side_effect_call_count"] == 0

    for running in list(bg._running):
        await running
    records = background_store._load_unlocked(background_store.background_tool_tasks_path())
    assert len(records) == 1
    assert records[0]["status"] == "completed"
    assert records[0]["approval_granted"] is True
    assert handler_calls == [True]
    assert bg._context_from_task(records[0]).turn_budget is None


def test_firewall_redaction_keeps_budget_fields() -> None:
    from pallas.product.llm.persona_output_firewall import redact_agent_trace_for_firewall

    redacted = redact_agent_trace_for_firewall({
        "status": "budget_exhausted",
        "budget_exhausted": True,
        "budget_exhaust_reason": "http_attempts_exhausted",
        "budget_http_attempts_used": 2,
        "budget_http_attempts_max": 6,
        "budget_completed_tool_calls": 1,
        "side_effect_started": True,
        "secret_payload": {"token": "x"},
        "messages": ["原话"],
    })
    assert redacted is not None
    assert redacted["budget_exhausted"] is True
    assert redacted["budget_exhaust_reason"] == "http_attempts_exhausted"
    assert redacted["budget_http_attempts_used"] == 2
    assert redacted["budget_http_attempts_max"] == 6
    assert redacted["budget_completed_tool_calls"] == 1
    assert redacted["side_effect_started"] is True
    assert "secret_payload" not in redacted
    assert "messages" not in redacted


@pytest.mark.asyncio
async def test_no_endpoint_prepare_deadline_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow_prepare(*_args, **_kwargs):
        await asyncio.sleep(30)
        return []

    monkeypatch.setattr("pallas.product.llm.providers_store.resolve_endpoint_for_task", lambda _task: None)
    monkeypatch.setattr(
        "pallas.product.llm.vision_messages.prepare_messages_for_provider_capabilities",
        slow_prepare,
    )
    budget = LlmTurnBudget(deadline_monotonic=time.monotonic() + 0.05, max_http_attempts=6)

    with pytest.raises(LlmTurnBudgetExceeded):
        await complete_with_tool_loop(
            system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            metadata={"tools_enabled": False, "bot_id": 1, "user_id": 2, "group_id": 3},
            cfg=LlmConfig(llm_model="m"),
            turn_budget=budget,
        )


@pytest.mark.asyncio
async def test_history_tool_without_budget_calls_provider_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.tools.context import ToolInvokeContext
    from pallas.product.llm.tools.history import handle_recent_summary

    _stub_history_repo(monkeypatch)
    cfg = LlmConfig(llm_model="m", llm_tools_history_daily_budget=2000)
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: cfg)
    posts = _patch_http(monkeypatch, lambda index: {"role": "assistant", "content": "总结。"})

    result = await handle_recent_summary({}, ToolInvokeContext(bot_id=99, group_id=42, user_id=11))

    assert result["result"]["summary"] == "总结。"
    assert posts == [1]
