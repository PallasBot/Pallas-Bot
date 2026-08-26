"""当前时间查询工具。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, register_tool

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext

TIMEZONE_NAME = "Asia/Shanghai"
_SHANGHAI_TZ = ZoneInfo(TIMEZONE_NAME)


def current_time_text() -> str:
    return datetime.now(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")


def register_time_tools() -> None:
    register_tool(
        LlmToolSpec(
            name="time.now",
            description="查询当前北京时间。",
            parameters={"type": "object", "properties": {}, "required": []},
            domains=frozenset({"time", "meta"}),
            handler=handle_time_now,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({"read_only"}),
            read_only=True,
            hints=frozenset({"现在几点", "当前时间", "现在时间", "几点了", "北京时间"}),
        )
    )


async def handle_time_now(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    del arguments, context
    try:
        now = datetime.now(_SHANGHAI_TZ)
    except Exception:
        return {"ok": False, "error": "clock_unavailable"}
    return {
        "ok": True,
        "result": {
            "iso": now.isoformat(),
            "readable": now.strftime("%Y年%m月%d日 %H:%M:%S"),
            "timezone": TIMEZONE_NAME,
            "timestamp": int(now.timestamp()),
        },
    }
