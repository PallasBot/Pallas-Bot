"""帮助图共用绘制工具（含 2× 超采样）。"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

from PIL import Image, ImageDraw

from . import help_theme as ht
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
    t = re.sub(r"\s+", " ", (text or "").strip().replace("\n", " ")).strip()
    if not t:
        return ""
    if draw.textlength(t, font=font) <= max_width:
        return t
    ell = "…"
    while t and draw.textlength(t + ell, font=font) > max_width:
        t = t[:-1]
    return (t + ell) if t else ell


def wrap_pixels(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """按像素宽度折行，不截断、不加省略号（正文长列表用）。"""
    t = (text or "").rstrip("\n")
    if not t:
        return []
    if max_width <= 0 or draw.textlength(t, font=font) <= max_width:
        return [t]
    lines: list[str] = []
    current = ""
    for ch in t:
        trial = current + ch
        if current and draw.textlength(trial, font=font) > max_width:
            lines.append(current)
            current = ch
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


@dataclass(slots=True)
class HelpCanvas:
    """逻辑坐标成图：内部按 RENDER_SCALE 放大绘制，finish 时缩回。"""

    image: Image.Image
    draw: ImageDraw.ImageDraw
    x1: int
    y1: int
    x2: int
    y2: int
    scale: int
    logical_width: int
    logical_height: int

    def u(self, n: int | float) -> int:
        return int(round(n * self.scale))

    def finish(self) -> Image.Image:
        if self.scale <= 1:
            return self.image.convert("RGB")
        return self.image.resize(
            (self.logical_width, self.logical_height),
            Image.Resampling.LANCZOS,
        ).convert("RGB")


def new_canvas(height: int, *, width: int | None = None) -> HelpCanvas:
    scale = max(1, int(ht.RENDER_SCALE))
    logical_w = ht.MENU_WIDTH if width is None else width
    logical_h = height
    canvas = Image.new("RGBA", (logical_w * scale, logical_h * scale), ht.CANVAS + (255,))
    draw = ImageDraw.Draw(canvas)
    pad = ht.MENU_PAD * scale
    x1, y1 = pad, pad
    x2, y2 = logical_w * scale - pad, logical_h * scale - pad
    dark = ht.help_visual_mode() == "dark"
    outline = ht.ACCENT if dark else ht.BORDER
    draw.rounded_rectangle(
        (x1, y1, x2, y2),
        radius=ht.MENU_FRAME_RADIUS * scale,
        fill=ht.SURFACE,
        outline=outline,
        width=max(1, 2 * scale),
    )
    if dark:
        band_h = 6 * scale
        draw.rounded_rectangle(
            (x1 + 2 * scale, y1 + 2 * scale, x2 - 2 * scale, y1 + 2 * scale + band_h),
            radius=3 * scale,
            fill=ht.TITLE_GLOW,
        )
    return HelpCanvas(
        image=canvas,
        draw=draw,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        scale=scale,
        logical_width=logical_w,
        logical_height=logical_h,
    )


def draw_hint_boxes(
    draw: ImageDraw.ImageDraw,
    *,
    x1: int,
    x2: int,
    start_y: int,
    hints: list[str],
    font_size: int = 18,
    scale: int = 1,
) -> int:
    cursor_y = start_y
    small_font = help_font(font_size)
    for hint in hints:
        box_top = cursor_y
        wrapped = textwrap.fill(hint, width=46)
        line_h = 24 * scale
        box_h = max(line_h + 12 * scale, wrapped.count("\n") * line_h + line_h + 12 * scale)
        draw.rounded_rectangle(
            (x1 + 12 * scale, box_top, x2 - 12 * scale, box_top + box_h),
            radius=10 * scale,
            fill=ht.QUOTE_BG,
        )
        draw.text((x1 + 24 * scale, box_top + 8 * scale), wrapped, fill=ht.TEXT, font=small_font)
        cursor_y = box_top + box_h + 10 * scale
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
    scale: int = 1,
) -> int:
    title_font = help_font(title_size)
    body_font = help_font(body_size)
    draw.text((x, y), title, fill=ht.TEXT_TITLE, font=title_font)
    cursor = y + (title_size + 8) * scale
    for line in (body or "").splitlines():
        if not line.strip():
            continue
        fitted = truncate_pixels(draw, line, body_font, max_x - x)
        draw.text((x, cursor), fitted, fill=ht.TEXT, font=body_font)
        cursor += line_h * scale
    return cursor + 8 * scale


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
    scale: int = 1,
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
            scale=scale,
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
        scale=scale,
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
    scale: int = 1,
) -> int:
    title_font = help_font(title_size)
    body_font = help_font(body_size)
    draw.text((x, y), title, fill=ht.TEXT_TITLE, font=title_font)
    cursor = y + (title_size + 8) * scale
    wrapped = textwrap.fill(strip_help_markdown((body or "").strip() or "暂无"), width=width_chars)
    for line in wrapped.splitlines():
        if not line.strip():
            continue
        fitted = truncate_pixels(draw, line, body_font, max_x - x)
        draw.text((x, cursor), fitted, fill=ht.TEXT, font=body_font)
        cursor += line_h * scale
    return cursor + 8 * scale


def content_inner_width(*, width: int | None = None) -> int:
    w = ht.DETAIL_WIDTH if width is None else width
    return w - ht.DETAIL_PAD * 2 - 24
