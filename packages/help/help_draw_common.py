"""帮助图 v3 共用绘制工具。"""

from __future__ import annotations

import re
import textwrap

from PIL import Image, ImageDraw

from .help_theme import (
    BORDER,
    CANVAS,
    DETAIL_PAD,
    DETAIL_WIDTH,
    MENU_FRAME_RADIUS,
    MENU_PAD,
    MENU_WIDTH,
    QUOTE_BG,
    SURFACE,
    TEXT,
    TEXT_TITLE,
)
from .plugin_visuals import help_font


def strip_help_markdown(text: str) -> str:
    """PIL 帮助图不渲染 Markdown，去掉常见行内强调标记。"""
    s = text or ""
    for _ in range(3):
        new = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        new = re.sub(r"__(.+?)__", r"\1", new)
        if new == s:
            break
        s = new
    return s


def truncate_pixels(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    t = re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()
    if not t:
        return ""
    if draw.textlength(t, font=font) <= max_width:
        return t
    ell = "…"
    while t and draw.textlength(t + ell, font=font) > max_width:
        t = t[:-1]
    return (t + ell) if t else ell


def new_canvas(height: int, *, width: int = MENU_WIDTH) -> tuple[Image.Image, ImageDraw.ImageDraw, int, int, int, int]:
    canvas = Image.new("RGBA", (width, height), CANVAS + (255,))
    draw = ImageDraw.Draw(canvas)
    x1, y1 = MENU_PAD, MENU_PAD
    x2, y2 = width - MENU_PAD, height - MENU_PAD
    draw.rounded_rectangle((x1, y1, x2, y2), radius=MENU_FRAME_RADIUS, fill=SURFACE, outline=BORDER, width=2)
    return canvas, draw, x1, y1, x2, y2


def draw_hint_boxes(
    draw: ImageDraw.ImageDraw,
    *,
    x1: int,
    x2: int,
    start_y: int,
    hints: list[str],
    font_size: int = 18,
) -> int:
    cursor_y = start_y
    small_font = help_font(font_size)
    for hint in hints:
        box_top = cursor_y
        wrapped = textwrap.fill(hint, width=46)
        line_h = 24
        box_h = max(line_h + 12, wrapped.count("\n") * line_h + line_h + 12)
        draw.rounded_rectangle((x1 + 12, box_top, x2 - 12, box_top + box_h), radius=10, fill=QUOTE_BG)
        draw.text((x1 + 24, box_top + 8), wrapped, fill=TEXT, font=small_font)
        cursor_y = box_top + box_h + 10
    return cursor_y


def measure_wrapped_text_height(text: str, *, width_chars: int, line_h: int) -> int:
    wrapped = textwrap.fill((text or "").strip() or "暂无", width=width_chars)
    lines = [ln for ln in wrapped.splitlines() if ln.strip()]
    return max(1, len(lines)) * line_h


def measure_preformatted_lines_height(body: str, *, line_h: int = 26) -> int:
    lines = [ln for ln in (body or "").splitlines() if ln.strip()]
    return max(1, len(lines)) * line_h


def measure_body_block_height(
    body: str,
    *,
    width_chars: int = 44,
    title_size: int = 24,
    line_h: int = 26,
) -> int:
    from .markdown_generator import _format_numbered_list_block, _is_numbered_list_block

    content = strip_help_markdown((body or "").strip() or "暂无")
    if _is_numbered_list_block(content):
        formatted = _format_numbered_list_block(content, width_chars)
        text_h = measure_preformatted_lines_height(formatted, line_h=line_h)
    else:
        text_h = measure_wrapped_text_height(content, width_chars=width_chars, line_h=line_h)
    return title_size + 8 + text_h + 8


def draw_preformatted_lines_block(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    max_x: int,
    title: str,
    body: str,
    title_size: int = 24,
    body_size: int = 18,
    line_h: int = 26,
) -> int:
    title_font = help_font(title_size)
    body_font = help_font(body_size)
    draw.text((x, y), title, fill=TEXT_TITLE, font=title_font)
    cursor = y + title_size + 8
    for line in (body or "").splitlines():
        if not line.strip():
            continue
        fitted = truncate_pixels(draw, line, body_font, max_x - x)
        draw.text((x, cursor), fitted, fill=TEXT, font=body_font)
        cursor += line_h
    return cursor + 8


def draw_body_block(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    max_x: int,
    title: str,
    body: str,
    width_chars: int = 44,
    title_size: int = 24,
    body_size: int = 18,
    line_h: int = 26,
) -> int:
    """绘制说明/用法等正文；有序列表保留 1. 2. 3. 结构与换行对齐。"""
    from .markdown_generator import _format_numbered_list_block, _is_numbered_list_block

    content = strip_help_markdown((body or "").strip() or "暂无")
    if _is_numbered_list_block(content):
        formatted = _format_numbered_list_block(content, width_chars)
        return draw_preformatted_lines_block(
            draw,
            x=x,
            y=y,
            max_x=max_x,
            title=title,
            body=formatted,
            title_size=title_size,
            body_size=body_size,
            line_h=line_h,
        )
    return draw_wrapped_block(
        draw,
        x=x,
        y=y,
        max_x=max_x,
        title=title,
        body=content,
        width_chars=width_chars,
        title_size=title_size,
        body_size=body_size,
        line_h=line_h,
    )


def draw_wrapped_block(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    max_x: int,
    title: str,
    body: str,
    width_chars: int = 44,
    title_size: int = 24,
    body_size: int = 18,
    line_h: int = 26,
) -> int:
    title_font = help_font(title_size)
    body_font = help_font(body_size)
    draw.text((x, y), title, fill=TEXT_TITLE, font=title_font)
    cursor = y + title_size + 8
    wrapped = textwrap.fill(strip_help_markdown((body or "").strip() or "暂无"), width=width_chars)
    for line in wrapped.splitlines():
        if not line.strip():
            continue
        fitted = truncate_pixels(draw, line, body_font, max_x - x)
        draw.text((x, cursor), fitted, fill=TEXT, font=body_font)
        cursor += line_h
    return cursor + 8


def content_inner_width(*, width: int = DETAIL_WIDTH) -> int:
    return width - DETAIL_PAD * 2 - 24
