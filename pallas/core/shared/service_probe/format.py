from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import ServiceProbeResult


def format_probe_detail(result: ServiceProbeResult) -> str:
    if result.runtime_detail:
        return result.runtime_detail
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


def format_probe_site_line(result: ServiceProbeResult) -> str:
    site = (result.site or "").strip() or "节点"
    return f"· {site}：{format_probe_detail(result)}"


def group_probe_results_by_category(
    results: list[ServiceProbeResult],
) -> list[tuple[str, list[ServiceProbeResult]]]:
    groups: list[tuple[str, list[ServiceProbeResult]]] = []
    index_by_category: dict[str, int] = {}
    for result in results:
        category = (result.category or "").strip() or "服务"
        if category in index_by_category:
            groups[index_by_category[category]][1].append(result)
        else:
            index_by_category[category] = len(groups)
            groups.append((category, [result]))
    return groups


def format_probe_category_block(category: str, items: list[ServiceProbeResult]) -> list[str]:
    lines = [f"【{category}】"]
    lines.extend(format_probe_site_line(r) for r in items)
    return lines


def format_probe_line(
    result: ServiceProbeResult,
    *,
    show_category: bool = True,
) -> str:
    if show_category and (result.category or "").strip():
        return "\n".join(format_probe_category_block(result.category.strip(), [result]))
    return format_probe_site_line(result)


def format_probe_lines(results: list[ServiceProbeResult]) -> list[str]:
    if not results:
        return []
    lines: list[str] = []
    for i, (category, items) in enumerate(group_probe_results_by_category(results)):
        if i > 0:
            lines.append("")
        lines.extend(format_probe_category_block(category, items))
    return lines


def format_probe_text(results: list[ServiceProbeResult]) -> str:
    if not results:
        return "未配置可探测的服务端点。"
    return "\n".join(format_probe_lines(results))
