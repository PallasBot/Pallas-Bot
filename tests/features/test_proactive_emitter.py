"""proactive_emitter 单出口与冷却限流。"""

from __future__ import annotations

import asyncio

import pytest

from pallas.product.llm import proactive_emitter as pe


@pytest.fixture(autouse=True)
def reset_proactive_state():
    pe._handlers.clear()
    pe._last_emit_at.clear()
    yield
    pe._handlers.clear()
    pe._last_emit_at.clear()


def test_emit_proactive_invokes_registered_handlers() -> None:
    seen: list[dict] = []

    async def handler(payload: dict) -> None:
        seen.append(payload)

    pe.register_proactive_handler("demo", handler)
    ok = asyncio.run(
        pe.emit_proactive(
            pe.ProactiveEmitContext(source="repeater", group_id=123, metadata={"k": "v"}),
        ),
    )
    assert ok is True
    assert seen == [{"source": "repeater", "group_id": 123, "user_id": None, "metadata": {"k": "v"}}]


def test_emit_proactive_respects_cooldown() -> None:
    calls = 0

    async def handler(_payload: dict) -> None:
        nonlocal calls
        calls += 1

    pe.register_proactive_handler("demo", handler)
    ctx = pe.ProactiveEmitContext(source="repeater")
    assert asyncio.run(pe.emit_proactive(ctx)) is True
    assert asyncio.run(pe.emit_proactive(ctx)) is False
    assert calls == 1
    assert pe.proactive_cooldown_remaining("repeater") > 0


def test_register_proactive_handler_replaces_same_name() -> None:
    order: list[str] = []

    async def first(_payload: dict) -> None:
        order.append("first")

    async def second(_payload: dict) -> None:
        order.append("second")

    pe.register_proactive_handler("demo", first)
    pe.register_proactive_handler("demo", second)
    asyncio.run(pe.emit_proactive(pe.ProactiveEmitContext(source="x")))
    assert order == ["second"]
