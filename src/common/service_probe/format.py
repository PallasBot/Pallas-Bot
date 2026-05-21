from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import ServiceProbeResult


def format_probe_detail(result: ServiceProbeResult) -> str:
    if result.ok and result.latency_ms is not None:
        line = f"{result.latency_ms}ms"
        if result.error:
            line += f"（{result.error}）"
        return line
    if result.status_code is not None:
        return f"HTTP {result.status_code}"
    if result.error:
        return result.error
    return "不可用"


def category_site_indent(category: str) -> int:
    """首行「类别 + 空格」宽度，备线等与主网关列对齐。"""
    name = (category or "").strip()
    return len(f"{name} ") if name else 0


def format_probe_line(
    result: ServiceProbeResult,
    *,
    show_category: bool = True,
    indent: int = 0,
) -> str:
    detail = format_probe_detail(result)
    site = (result.site or "").strip()
    if show_category and (result.category or "").strip():
        return f"{result.category.strip()} {site}：{detail}"
    pad = " " * max(0, indent)
    return f"{pad}{site}：{detail}"


def format_probe_lines(results: list[ServiceProbeResult]) -> list[str]:
    lines: list[str] = []
    prev_category: str | None = None
    indent = 0
    for result in results:
        category = (result.category or "").strip()
        show_category = category != prev_category
        if show_category:
            indent = category_site_indent(category)
        lines.append(format_probe_line(result, show_category=show_category, indent=indent))
        prev_category = category
    return lines


def format_probe_text(results: list[ServiceProbeResult]) -> str:
    if not results:
        return "未配置可探测的服务端点。"
    return "\n".join(format_probe_lines(results))
