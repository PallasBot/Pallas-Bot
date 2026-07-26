"""受控网络工具。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSpec, register_tool

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext


_WEB_SEARCH_HINTS = frozenset({
    "搜一下",
    "搜索一下",
    "帮我搜",
    "帮我搜索",
    "联网搜",
    "网上搜",
    "上网搜",
    "百度一下",
    "google一下",
    "谷歌一下",
    "查网页",
    "搜网页",
    "搜索",
})


def register_web_tools() -> None:
    register_tool(
        LlmToolSpec(
            name="web.search",
            description="搜索公开网页，返回结构化结果。未配置时返回 web_search_unconfigured，禁止口头装作搜过。",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            domains=frozenset({"web", "chat"}),
            handler=handle_web_search,
            capabilities=frozenset({ToolCapability.READ_ONLY.value, ToolCapability.EXTERNAL_NETWORK.value}),
            hints=_WEB_SEARCH_HINTS,
            estimated_duration_ms=3000,
            background_ok=True,
        )
    )
    register_tool(
        LlmToolSpec(
            name="web.fetch",
            description="抓取一个 http(s) 网页并返回有限长度文本。",
            parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            domains=frozenset({"web", "chat"}),
            handler=handle_web_fetch,
            capabilities=frozenset({ToolCapability.READ_ONLY.value, ToolCapability.EXTERNAL_NETWORK.value}),
            hints=frozenset({"打开网页", "抓取网页", "读取链接", "打开链接"}),
            estimated_duration_ms=5000,
            background_ok=True,
        )
    )


async def handle_web_search(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    del context
    query = str((arguments or {}).get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query_required"}
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value

    endpoint = str(repo_env_raw_value("WEB_SEARCH_API_URL") or os.environ.get("WEB_SEARCH_API_URL") or "").strip()
    api_key = str(repo_env_raw_value("TAVILY_API_KEY") or os.environ.get("TAVILY_API_KEY") or "").strip()
    if not endpoint or not api_key:
        return {
            "ok": False,
            "error": "web_search_unconfigured",
            "user_hint": "联网搜索尚未配置，不要假装搜过；如实告诉用户暂时搜不了。",
        }
    try:
        import httpx

        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(
                endpoint, json={"query": query}, headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            return {"ok": True, "result": response.json()}
    except Exception as exc:
        return {"ok": False, "error": f"web_search_failed:{exc}"}


async def handle_web_fetch(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    del context
    from urllib.parse import urlparse

    url = str((arguments or {}).get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"ok": False, "error": "http_url_required"}
    try:
        import httpx

        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            text = response.text[:20000]
            return {
                "ok": True,
                "result": {"url": str(response.url), "text": text, "truncated": len(response.text) > len(text)},
            }
    except ImportError:
        return {"ok": False, "error": "httpx_unavailable"}
    except Exception as exc:
        return {"ok": False, "error": f"web_fetch_failed:{exc}"}
