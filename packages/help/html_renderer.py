"""帮助图 HTML/Playwright 渲染。"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import Image

from . import help_theme as ht
from .help_draw_common import strip_help_markdown
from .help_tags import group_rows_by_help_tag, help_tag_label
from .html_theme import get_html_theme, html_theme_revision
from .plugin_visuals import load_help_plugin_icon

HTML_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
HTML_TEMPLATE_NAME = "help.html"
HTML_TEMPLATE_PATH = HTML_TEMPLATE_DIR / HTML_TEMPLATE_NAME
HTML_VIEWPORT_WIDTH = 920
HTML_WIDE_VIEWPORT_WIDTH = 1180
HTML_DEVICE_SCALE_FACTOR = 2

_UNORDERED_ITEM_RE = re.compile(r"^\s*[-*•·]\s+(.+)$")
_ORDERED_ITEM_RE = re.compile(r"^\s*\d+[.)]\s+(.+)$")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_FENCED_CODE_RE = re.compile(r"^\s*```(?:[^\s`]*)?\s*$")
_DESCRIPTION_SUMMARY_LIMIT = 96
# 命令候选分隔（两侧带空白的竖线），避免切碎 <傀影|水月> 这类占位符
_CMD_CANDIDATE_RE = re.compile(r"\s+\|\s+")


def _theme_context() -> dict[str, str]:
    return get_html_theme()


def html_template_revision() -> str:
    try:
        stat = HTML_TEMPLATE_PATH.stat()
        digest = hashlib.sha256(HTML_TEMPLATE_PATH.read_bytes()).hexdigest()[:16]
    except OSError:
        return "missing"
    return f"{stat.st_mtime_ns}:{stat.st_size}:{digest}"


def html_assets_revision() -> str:
    return f"template={html_template_revision()}|theme={html_theme_revision()}"


def _inline_body_html(text: str) -> str:
    escaped = html.escape(text, quote=False)
    return _INLINE_CODE_RE.sub(r"<code>\1</code>", escaped)


def _display_command(text: str) -> str:
    """返回帮助图中展示的命令，不显示 Markdown 行内代码标记。"""
    return _INLINE_CODE_RE.sub(r"\1", strip_help_markdown((text or "").strip()))


def _split_say_candidates(text: str) -> tuple[str, list[str]]:
    """把「主命令 | 别名」拆为 (主命令, [别名…])；无法拆分时整体作为主命令。"""
    cleaned = _display_command(text)
    parts = [part.strip() for part in _CMD_CANDIDATE_RE.split(cleaned) if part.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1:]
    return cleaned, []


def _command_examples(detail: str, primary: str, func_name: str) -> list[str]:
    candidates = re.findall(r"`([^`\n]+)`", detail or "")
    examples: list[str] = []
    for candidate in candidates:
        command = candidate.strip()
        if not command or (primary not in command and func_name not in command):
            continue
        if command not in examples:
            examples.append(command)
    return examples[:4]


def _description_display(text: str) -> tuple[str, bool]:
    """返回页头摘要及是否需要在正文保留完整说明。"""
    full = strip_help_markdown((text or "").strip() or "暂无描述")
    compact = " ".join(line.strip() for line in full.splitlines() if line.strip())
    if len(compact) <= _DESCRIPTION_SUMMARY_LIMIT:
        return compact, compact != full
    summary = compact[: _DESCRIPTION_SUMMARY_LIMIT - 1].rstrip() + "…"
    return summary, True


def _body_html(body: str) -> str:
    content = strip_help_markdown((body or "").strip() or "暂无")
    blocks: list[str] = []
    paragraph: list[str] = []
    list_tag: str | None = None
    code_block: list[str] | None = None
    blockquote: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        blocks.append(f"<p>{'<br>'.join(_inline_body_html(line) for line in paragraph)}</p>")
        paragraph.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag is not None:
            blocks.append(f"</{list_tag}>")
            list_tag = None

    def close_code_block() -> None:
        nonlocal code_block
        if code_block is not None:
            escaped = html.escape("\n".join(code_block), quote=False)
            blocks.append(f"<pre><code>{escaped}</code></pre>")
            code_block = None

    def flush_blockquote() -> None:
        if not blockquote:
            return
        blocks.append(f"<blockquote>{'<br>'.join(_inline_body_html(line) for line in blockquote)}</blockquote>")
        blockquote.clear()

    for raw_line in content.splitlines():
        if code_block is not None:
            if _FENCED_CODE_RE.match(raw_line):
                close_code_block()
            else:
                code_block.append(raw_line.rstrip())
            continue

        line = raw_line.strip()
        if not line:
            flush_paragraph()
            close_list()
            flush_blockquote()
            continue

        if _FENCED_CODE_RE.match(raw_line):
            flush_paragraph()
            close_list()
            flush_blockquote()
            code_block = []
            continue

        if line.startswith(">"):
            flush_paragraph()
            close_list()
            blockquote.append(line[1:].lstrip())
            continue

        flush_blockquote()

        unordered = _UNORDERED_ITEM_RE.match(line)
        ordered = _ORDERED_ITEM_RE.match(line)
        if unordered or ordered:
            flush_paragraph()
            target_tag = "ul" if unordered else "ol"
            if list_tag != target_tag:
                close_list()
                blocks.append(f"<{target_tag}>")
                list_tag = target_tag
            item_text = unordered.group(1) if unordered else ordered.group(1)
            blocks.append(f"<li>{_inline_body_html(item_text)}</li>")
            continue

        close_list()
        paragraph.append(line)

    flush_paragraph()
    close_list()
    flush_blockquote()
    close_code_block()
    return "".join(blocks) or "<p>暂无</p>"


def _image_data_uri(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.convert("RGBA").save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _plugin_icon(plugin: Any, *, size: int, label: str) -> str:
    return _image_data_uri(load_help_plugin_icon(plugin, size=size, label=label))


def _base_context(kind: str, *, title: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": title,
        "viewport_width": HTML_VIEWPORT_WIDTH if kind == "function" else HTML_WIDE_VIEWPORT_WIDTH,
        "visual_mode": ht.help_visual_mode(),
        "theme": _theme_context(),
    }


def build_menu_context(
    menu_rows: list,
    *,
    show_ignored: bool,
    total_plugin_count: int,
    total_enabled_count: int,
) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    for group_index, (tag, rows) in enumerate(group_rows_by_help_tag(menu_rows, tag_of=lambda row: row.help_tag), 1):
        row_contexts = [
            {
                "index": row.index,
                "index_label": f"{row.index:02d}",
                "display_name": row.display_name,
                "description": strip_help_markdown(row.description),
                "enabled": row.enabled,
                "status_code": "ON" if row.enabled else "OFF",
                "status": "ON 已启用" if row.enabled else "OFF 已停用",
                "icon": _plugin_icon(row.plugin, size=64, label=row.display_name),
            }
            for row in rows
        ]
        layout_rows: list[list[dict[str, Any]]] = []
        cursor = 0
        while cursor < len(row_contexts):
            remaining = len(row_contexts) - cursor
            width = 2 if remaining > 3 and remaining % 3 == 1 else min(3, remaining)
            layout_rows.append(row_contexts[cursor : cursor + width])
            cursor += width
        groups.append({
            "number": f"{group_index:02d}",
            "label": help_tag_label(tag),
            "count": len(rows),
            "rows": row_contexts,
            "layout_rows": layout_rows,
        })

    context = _base_context("menu", title="牛牛帮助" if not show_ignored else "牛牛帮助（超级用户）")
    first_open = next(
        (row["display_name"] for group in groups for row in group["rows"] if row["enabled"]),
        None,
    )
    context.update({
        "eyebrow": "PALLAS / HELP / INDEX",
        "stats": f"共 {total_plugin_count} 个 · 启用 {total_enabled_count}",
        "stats_label": "启用状态",
        "stats_value": f"{total_enabled_count} / {total_plugin_count}",
        "stats_note": "已启用 / 总插件",
        "stats_big": str(total_enabled_count),
        "stats_caption": "项功能开放",
        "stats_sub": f"共 {total_plugin_count} 项 · 启用 {total_enabled_count}",
        "try_command": f"牛牛帮助 {first_open}" if first_open else "牛牛帮助",
        "meta": "牛牛帮助 + 序号/插件名 → 功能；开关：牛牛开启/关闭 + 插件名",
        "groups": groups,
        "show_ignored": show_ignored,
        "footer": "发 牛牛帮助 + 插件名 查看功能 · 任意层级发 牛牛帮助 回总览",
        "footer_items": [
            {"label": "详情", "command": "牛牛帮助 + 序号/插件名"},
            {"label": "启停", "command": "牛牛开启/关闭 + 插件名"},
            {"label": "总览", "command": "牛牛帮助"},
        ],
    })
    return context


def _section_context(title: str, body: str, number: int | None = None) -> dict[str, str]:
    clean_body = strip_help_markdown((body or "").strip() or "暂无")
    context = {
        "title": title,
        "body": clean_body,
        "body_html": _body_html(clean_body),
    }
    if number is not None:
        context["number"] = f"{number:02d}"
    return context


def _function_meta(*values: str) -> str:
    return " · ".join(value for value in values if value and value != "—")


def _status_code(enabled: bool | None) -> str | None:
    if enabled is True:
        return "ON"
    if enabled is False:
        return "OFF"
    return None


def _metadata_cells(data: Any) -> list[dict[str, str]]:
    fields = (
        ("SCENE", "触发场景", data.scene),
        ("ACCESS", "何人可用", data.perm),
        ("COOLDOWN", "冷却时间", data.cooldown),
    )
    return [
        {"label": label, "title": title, "value": strip_help_markdown(value)}
        for label, title, value in fields
        if value and value != "—"
    ]


def _footer_text(items: list[dict[str, str]]) -> str:
    return " · ".join(f"{item['label']}：{item['command']}" for item in items)


def build_plugin_context(data: Any) -> dict[str, Any]:
    status = None
    if data.enabled is not None:
        status = "已启用" if data.enabled else "已停用"
    if data.enabled is True:
        meta = f"关闭：牛牛关闭 {data.display_name}"
    elif data.enabled is False:
        meta = f"开启：牛牛开启 {data.display_name}"
    else:
        meta = f"牛牛帮助 {data.display_name} + 功能序号/名称"

    description, keep_description_section = _description_display(data.description)
    sections: list[dict[str, str]] = []
    next_section_number = 2 if data.functions else 1
    if keep_description_section:
        sections.append(_section_context("说明", data.description, next_section_number))
        next_section_number += 1
    if not data.functions:
        sections.append(_section_context("插件内用法", data.usage, next_section_number))
        next_section_number += 1
    sections.extend(
        _section_context(title, body, index)
        for index, (title, body) in enumerate(data.extra_sections, next_section_number)
    )
    footer_items = [{"label": "总览", "command": "牛牛帮助"}]

    function_rows: list[dict[str, Any]] = [
        {
            "index": row.index,
            "index_label": f"{row.index:02d}",
            "func": strip_help_markdown(row.func),
            "say": _display_command(row.say),
            "say_main": _split_say_candidates(row.say)[0],
            "scene": strip_help_markdown(row.scene),
            "perm": strip_help_markdown(row.perm),
            "meta": _function_meta(
                strip_help_markdown(row.scene),
                strip_help_markdown(row.perm),
            ),
            "brief": (
                ""
                if strip_help_markdown(row.brief) == strip_help_markdown(row.func)
                else strip_help_markdown(row.brief)
            ),
            "group": str(getattr(row, "group", "") or "").strip(),
        }
        for row in data.functions
    ]
    default_group_label = "功能一览"
    grouped_by: dict[str, list[dict[str, Any]]] = {}
    for row in function_rows:
        grouped_by.setdefault(row["group"] or default_group_label, []).append(row)
    group_items = list(grouped_by.items())
    if len(group_items) > 1:
        group_items = [("其他功能" if label == default_group_label else label, rows) for label, rows in group_items]
    function_groups: list[dict[str, Any]] = [{"label": label, "rows": rows} for label, rows in group_items]
    footer_nav = [{"label": "返回总览", "command": "牛牛帮助", "primary": True}]
    if data.enabled is not None:
        verb = "关闭" if data.enabled else "开启"
        footer_nav.append({"label": verb + "插件", "command": f"牛牛{verb} {data.display_name}"})

    context = _base_context("plugin", title=data.display_name)
    context.update({
        "eyebrow": "PALLAS / PLUGIN / DOSSIER",
        "description": description,
        "function_section_number": "01" if data.functions else None,
        "icon": _plugin_icon(data.plugin, size=88, label=data.display_name),
        "status": status,
        "status_code": _status_code(data.enabled),
        "meta": meta,
        "function_count": len(data.functions),
        "function_count_value": f"{len(data.functions):02d}",
        "function_count_label": "FUNCTIONS",
        "functions": function_rows,
        "function_groups": function_groups,
        "sections": sections,
        "footer_items": footer_items,
        "footer": _footer_text(footer_items),
        "footer_nav": footer_nav,
        "footer_text": " · ".join(f"{item['label']}：{item['command']}" for item in footer_nav),
    })
    return context


def build_function_context(data: Any) -> dict[str, Any]:
    chips = [strip_help_markdown(value) for value in (data.scene, data.perm, data.cooldown) if value and value != "—"]
    sections = [_section_context("怎么用", data.detail, 1)] if data.detail else []
    sections.extend(
        _section_context(title, body, index)
        for index, (title, body) in enumerate(data.extra_sections, len(sections) + 1)
    )
    primary, aliases = _split_say_candidates(data.say)
    examples = _command_examples(data.detail, primary, data.func_name)
    navigation = [{"label": "返回插件", "command": f"牛牛帮助 {data.display_name}", "primary": True}]
    if data.index > 1:
        navigation.append({"label": "上一项", "command": f"牛牛帮助 {data.display_name} {data.index - 1}"})
    if data.index < data.total:
        navigation.append({"label": "下一项", "command": f"牛牛帮助 {data.display_name} {data.index + 1}"})
    navigation.append({"label": "返回总览", "command": "牛牛帮助", "primary": True})

    context = _base_context("function", title=data.func_name)
    context.update({
        "eyebrow": "PALLAS / COMMAND / BRIEF",
        "display_name": data.display_name,
        "breadcrumb": f"帮助总览 / {data.display_name} / {data.func_name}",
        "index": data.index,
        "index_label": f"{data.index:02d}",
        "total": data.total,
        "total_label": f"{data.total:02d}",
        "chips": chips,
        "metadata": _metadata_cells(data),
        "command_label": "直接发送",
        "say": _display_command(data.say or "—"),
        "primary_command": primary or "—",
        "alias_commands": aliases,
        "examples": examples,
        "brief": strip_help_markdown(data.brief),
        "sections": sections,
        "footer_items": navigation,
        "footer": _footer_text(navigation),
        "footer_nav": navigation,
    })
    return context


async def render_help_template(context: dict[str, Any]) -> bytes:
    """用项目统一的 htmlrender 后端渲染帮助模板。"""
    from nonebot_plugin_htmlrender.render import render_template

    viewport_width = int(
        context.get("viewport_width")
        or (HTML_VIEWPORT_WIDTH if context.get("kind") == "function" else HTML_WIDE_VIEWPORT_WIDTH)
    )

    return await render_template(
        str(HTML_TEMPLATE_DIR),
        template_name=HTML_TEMPLATE_NAME,
        templates=context,
        pages={
            "viewport": {"width": viewport_width, "height": 10},
            "base_url": "about:blank",
        },
        image_type="png",
        device_scale_factor=HTML_DEVICE_SCALE_FACTOR,
        resolve_resources=False,
    )


__all__ = [
    "HTML_DEVICE_SCALE_FACTOR",
    "HTML_TEMPLATE_DIR",
    "HTML_TEMPLATE_NAME",
    "HTML_TEMPLATE_PATH",
    "HTML_VIEWPORT_WIDTH",
    "HTML_WIDE_VIEWPORT_WIDTH",
    "build_function_context",
    "build_menu_context",
    "build_plugin_context",
    "html_assets_revision",
    "html_template_revision",
    "render_help_template",
]
