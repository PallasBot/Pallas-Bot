from __future__ import annotations

from typing import Protocol


class ReviewProvider(Protocol):
    """远程文本审查：返回 True 表示应拦截该条消息。"""

    id: str

    async def is_blocked(self, *, plain_text: str, raw_message: str) -> bool:
        """实现可发 HTTP；异常由 ``api_chain.run_review_chain`` 按 fail_open 处理。"""
