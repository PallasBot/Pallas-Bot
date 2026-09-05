"""兼容 AI 扩展回调 Bot 执行 LLM tools；内核 tool loop 不经此路由。"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field


class LlmToolExecuteRequest(BaseModel):
    name: str = Field(min_length=1)
    arguments: dict = Field(default_factory=dict)
    bot_id: int
    group_id: int | None = None
    user_id: int
    request_id: str = ""


def register_llm_tools_http() -> None:
    from nonebot import get_app

    app = get_app()

    @app.post("/pallas/api/internal/llm/tools/execute")
    async def llm_tool_execute_route(body: LlmToolExecuteRequest) -> dict:
        from pallas.product.llm.tools.context import ToolInvokeContext
        from pallas.product.llm.tools.registry import execute_tool_async

        if body.name.startswith("social."):
            raise HTTPException(status_code=403, detail="social_tools_require_task_context")
        ctx = ToolInvokeContext(
            bot_id=body.bot_id,
            group_id=body.group_id,
            user_id=body.user_id,
            request_id=body.request_id,
        )
        result = await execute_tool_async(body.name, body.arguments, context=ctx)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result)
        return result
